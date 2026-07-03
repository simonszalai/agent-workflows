#!/usr/bin/env node
// mcp-gateway — one local daemon that fronts all remote MCP servers for every
// workspace/session, so clients (Claude Code / Cursor / Codex) connect over
// `type: http` to 127.0.0.1 instead of each spawning its own `mcp-remote` child.
//
// Why this exists: each workspace × server × session used to exec a separate
// `mcp-remote` stdio bridge (~60 node procs observed), and N bridges hammering
// the single small autodev-memory instance starved it (writes hung). This daemon
// replaces all of them: ONE process, secrets loaded ONCE, upstream TCP pooled via
// a shared keep-alive agent, and project identity carried in the URL path so
// project-scoped servers (render, postgres) still route to the right creds.
//
// It is a TRANSPARENT streaming reverse proxy: it relays the MCP-over-HTTP bytes
// (POST tool calls, GET SSE streams, mcp-session-id headers) unchanged except for
// swapping the client's Authorization for the route's upstream credential. That
// means it does not need to model each upstream's stateless/stateful session
// semantics — it just pipes.
//
// Routing table: routes.json next to this file (see loadRoutes). Each route maps
// a path prefix -> { target (upstream base URL), authEnv (env var holding the
// bearer token) }. The path prefix is "<project>/<server>" (or "shared/<server>"),
// so config URLs look like http://127.0.0.1:8765/ts/render.
//
// Secrets: read from process.env (the launchd plist / wrapper loads the 1Password
// mount once and exports them). Tokens never live in this file or in routes.json.

import http from "node:http"
import https from "node:https"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"
import { spawn, execFileSync } from "node:child_process"
import { Transform } from "node:stream"
import { encodeAutodevWriteBody } from "./waf-encode.mjs"

const __dirname = dirname(fileURLToPath(import.meta.url))

const HOST = process.env.MCP_GATEWAY_HOST || "127.0.0.1"
const PORT = Number(process.env.MCP_GATEWAY_PORT || 8765)
// Optional shared secret so only configured clients (which send the same header)
// can use the daemon's upstream credentials. Empty = no local auth (localhost only).
const LOCAL_TOKEN = process.env.MCP_GATEWAY_TOKEN || ""

// One pooled agent per protocol, shared across ALL routes and sessions. This is
// the connection pooling: bounded keep-alive sockets to each upstream host
// instead of one fresh client per workspace. maxFreeSockets caps how many idle
// sockets we retain per origin — keeping it small limits how many stale/half-open
// sockets can pile up when an upstream (e.g. a Render instance) is recycled.
const httpsAgent = new https.Agent({ keepAlive: true, maxSockets: 32, maxFreeSockets: 8, keepAliveMsecs: 30_000 })
const httpAgent = new http.Agent({ keepAlive: true, maxSockets: 32, maxFreeSockets: 8, keepAliveMsecs: 30_000 })

// Time-to-first-byte guards. A pooled keep-alive socket whose peer was silently
// torn down (Render idle-spindown / instance recycle behind Cloudflare, where TCP
// keepalive can't detect the dead origin) black-holes our write: the request
// would otherwise hang until OS TCP retransmit exhaustion (minutes). attempt 1
// uses a short guard so we fail fast and retry; the retry opens a fresh socket
// and uses a longer guard that also tolerates a genuine cold start.
const FIRST_BYTE_MS = Number(process.env.MCP_GATEWAY_FIRST_BYTE_MS || 10_000)
const RETRY_BYTE_MS = Number(process.env.MCP_GATEWAY_RETRY_BYTE_MS || 45_000)
// Connection-level failures that are safe to retry on a fresh socket (only ever
// before any response byte has been relayed to the client).
const RETRYABLE = new Set(["ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "EPIPE", "ECONNABORTED", "EHOSTUNREACH", "ENETUNREACH"])

function loadRoutes() {
	const raw = JSON.parse(readFileSync(join(__dirname, "routes.json"), "utf8"))
	// Sort prefixes longest-first so "/ts/postgres_prod_prefect" wins over "/ts".
	// Keys starting with "_" are comments, not routes.
	return Object.entries(raw.routes)
		.filter(([prefix]) => !prefix.startsWith("_"))
		.map(([prefix, def]) => {
			const r = { prefix: prefix.replace(/^\/|\/$/g, ""), ...def }
			// `spawn` routes are local children we supervise; their proxy target is the
			// loopback port the child binds. Derive it so the proxy path is uniform.
			if (r.spawn && !r.target) r.target = `http://127.0.0.1:${r.spawn.port}`
			return r
		})
		.sort((a, b) => b.prefix.length - a.prefix.length)
}

let ROUTES = loadRoutes()

function log(...args) {
	console.log(new Date().toISOString(), ...args)
}

// --- Phase 2: locally-supervised stdio MCP children (postgres-mcp over SSE) -----------
// `spawn` routes are NOT remote upstreams: the daemon launches one long-lived child per
// route, binds it to a loopback port, and proxies to it. This replaces the per-workspace
// `project-mcp ts postgres_*` stdio spawns — secrets are resolved ONCE (start-gateway.sh
// exports DATABASE_URIs), children are daemon-owned (so they die with the daemon instead
// of orphaning), and the DB connection pool is shared across every workspace's sessions.
const ACCESS_MODES = new Set(["restricted", "unrestricted"])
const ALT_ACCESS_MODE_PORT_OFFSET = Number(process.env.MCP_GATEWAY_ALT_ACCESS_MODE_PORT_OFFSET || 1000)

// key -> { proc, port, restarts, aliveTimer, prefix, accessMode }
// Default children keep the historical key (`prefix`) for log/readability; dynamic
// client-selected access-mode children use `${prefix}::${accessMode}`.
const children = new Map()
let shuttingDown = false

function defaultAccessMode(route) {
	return route.spawn?.accessMode || "restricted"
}

function childKey(route, accessMode = defaultAccessMode(route)) {
	return accessMode === defaultAccessMode(route) ? route.prefix : `${route.prefix}::${accessMode}`
}

function portForAccessMode(route, accessMode = defaultAccessMode(route)) {
	const s = route.spawn
	if (accessMode === defaultAccessMode(route)) return s.port
	if (s.ports?.[accessMode]) return s.ports[accessMode]
	return s.port + ALT_ACCESS_MODE_PORT_OFFSET
}

function parseAccessMode(url) {
	return (
		url.searchParams.get("access_mode") ||
		url.searchParams.get("accessMode") ||
		url.searchParams.get("postgres_access_mode") ||
		url.searchParams.get("postgresAccessMode") ||
		""
	).trim().toLowerCase()
}

function removeAccessModeParams(url) {
	for (const key of ["access_mode", "accessMode", "postgres_access_mode", "postgresAccessMode"]) {
		url.searchParams.delete(key)
	}
}

function accessModeForRequest(route, url) {
	if (!route.spawn) return null
	const requested = parseAccessMode(url)
	if (!requested) return defaultAccessMode(route)
	if (!ACCESS_MODES.has(requested)) {
		throw new Error(`invalid access_mode=${requested}; expected restricted or unrestricted`)
	}
	return requested
}

// Reap stray children from a previously-crashed daemon so their ports are free. We match
// the exact `--sse-port <port>` we are about to bind, so we never touch another project's
// or another tool's processes. (The daemon itself has no `--sse-port` in its argv.)
function reapStrayChildren(ports) {
	for (const port of ports) {
		let out = ""
		try {
			// NOTE: macOS pgrep uses BSD extended regex — no `\b`. Anchor the port with a
			// TRAILING SPACE instead (our children always pass `--sse-port <port> --access-mode…`,
			// so the port is always followed by a space). This both works on BSD ERE and stops
			// `8811` from matching `88110`.
			out = execFileSync("pgrep", ["-f", `postgres-mcp.*--sse-port ${port} `], { encoding: "utf8" })
		} catch {
			continue // pgrep exits non-zero when nothing matches
		}
		for (const pid of out.split("\n").map((s) => s.trim()).filter(Boolean)) {
			try {
				process.kill(Number(pid), "SIGTERM")
				log(`reaped stray postgres-mcp pid=${pid} (:${port})`)
			} catch {}
		}
	}
}

function startSpawnRoute(route, requestedAccessMode = defaultAccessMode(route)) {
	const s = route.spawn
	const accessMode = requestedAccessMode || defaultAccessMode(route)
	const key = childKey(route, accessMode)
	const port = portForAccessMode(route, accessMode)
	const url = process.env[s.urlEnv]
	if (!url) {
		log(`spawn ${route.prefix} (${accessMode}): env ${s.urlEnv} is unset — route will 502 until the daemon is restarted with it set`)
		return null
	}
	const existing = children.get(key)
	if (existing?.proc && existing.proc.exitCode === null) return existing
	reapStrayChildren([port])
	const bin = s.bin || process.env.POSTGRES_MCP_BIN || "postgres-mcp"
	const args = ["--transport", "sse", "--sse-host", "127.0.0.1", "--sse-port", String(port), "--access-mode", accessMode]
	// DATABASE_URI goes in the env, never argv, so the connection string stays out of `ps`.
	const proc = spawn(bin, args, { env: { ...process.env, DATABASE_URI: url }, stdio: ["ignore", "pipe", "pipe"] })

	const entry = children.get(key) || { restarts: 0 }
	entry.proc = proc
	entry.port = port
	entry.prefix = route.prefix
	entry.accessMode = accessMode
	children.set(key, entry)

	const tag = `[${key}]`
	proc.stdout.on("data", (d) => log(tag, String(d).trimEnd()))
	proc.stderr.on("data", (d) => log(tag, String(d).trimEnd()))
	// Reset the restart counter once a child has been stable for a minute, so an
	// occasional crash much later doesn't inherit a long backoff.
	entry.aliveTimer = setTimeout(() => { entry.restarts = 0 }, 60_000)

	proc.on("exit", (code, sig) => {
		clearTimeout(entry.aliveTimer)
		if (shuttingDown) return
		const backoff = Math.min(30_000, 500 * 2 ** entry.restarts)
		entry.restarts += 1
		log(`spawn ${key} exited (code=${code} sig=${sig}); respawning in ${backoff}ms`)
		setTimeout(() => { if (!shuttingDown) startSpawnRoute(route, accessMode) }, backoff)
	})
	proc.on("error", (err) => {
		// spawn failure (e.g. ENOENT: bad POSTGRES_MCP_BIN) emits "error" but NOT "exit",
		// so the exit handler never runs. Clear the alive-timer and drop the stale Map entry
		// so the route isn't wedged forever — a later SIGHUP (or restart) can retry it.
		clearTimeout(entry.aliveTimer)
		if (children.get(key) === entry) children.delete(key)
		log(`spawn ${key} failed: ${String(err.message || err)}`)
	})
	log(`spawned ${key} -> postgres-mcp sse 127.0.0.1:${port} (${accessMode})`)
	return entry
}

function ensureSpawnRoute(route, accessMode) {
	const key = childKey(route, accessMode)
	const existing = children.get(key)
	if (existing?.proc && existing.proc.exitCode === null) return existing
	return startSpawnRoute(route, accessMode)
}

function startAllSpawnRoutes() {
	const spawnRoutes = ROUTES.filter((r) => r.spawn)
	if (!spawnRoutes.length) return
	reapStrayChildren(spawnRoutes.map((r) => r.spawn.port))
	for (const r of spawnRoutes) startSpawnRoute(r)
}

function shutdown(sig) {
	if (shuttingDown) return
	shuttingDown = true
	const signum = sig === "SIGINT" ? 2 : 15
	log(`received ${sig}; stopping ${children.size} child(ren) and exiting`)
	for (const { proc } of children.values()) {
		try { proc.kill("SIGTERM") } catch {}
	}
	// Exit with 128+signum (NOT 0) so launchd's KeepAlive(SuccessfulExit=false) still
	// auto-restarts after an external kill — matching the pre-Phase-2 behavior where the
	// signal itself (no handler) produced an "unsuccessful" exit. We just reap our
	// children first so they don't orphan. A real `launchctl unload` removes the job (no
	// restart); system shutdown won't restart either.
	setTimeout(() => process.exit(128 + signum), 1500).unref()
}

// Rewrite the SSE `endpoint` event so a path-prefixed client POSTs back through THIS
// route. postgres-mcp's legacy SSE transport advertises an absolute POST path
// (`event: endpoint\ndata: /messages/?session_id=...`); resolved against the gateway
// origin that would be `/messages/...` — a 404 here. We prepend the route prefix so it
// becomes `/<prefix>/messages/?session_id=...`. Only the first (tiny, ASCII) endpoint
// event is buffered/scanned; once rewritten, all further bytes pass through untouched so
// SSE framing/flushing is unaffected. The trailing newline in the match guarantees we
// only rewrite a COMPLETE data line (never a path split across chunks).
function endpointPathForClient(prefix, accessMode, upstreamPath) {
	const u = new URL(prefix + upstreamPath, "http://mcp-gateway.local")
	if (accessMode) u.searchParams.set("access_mode", accessMode)
	return u.pathname + u.search
}

function sseEndpointRewriter(prefix, accessMode) {
	let done = false
	let buf = ""
	const CAP = 64 * 1024
	// `^…/m` anchors to a line start so we only match a real `endpoint` event frame, never
	// the same text appearing inside an SSE comment line (`: event: endpoint`).
	const re = /(^event:[ \t]*endpoint[ \t]*\r?\n)(data:[ \t]*)(\/[^\r\n]*)(\r?\n)/m
	const finish = (self) => { self.push(buf); buf = ""; done = true }
	return new Transform({
		transform(chunk, _enc, cb) {
			if (done) { this.push(chunk); return cb() }
			buf += chunk.toString("utf8")
			if (re.test(buf)) {
				buf = buf.replace(re, (_m, ev, d, p, nl) => ev + d + endpointPathForClient(prefix, accessMode, p) + nl)
				finish(this)
			} else if (buf.length >= CAP) {
				finish(this) // endpoint event not found in a reasonable window — pass through as-is
			}
			cb()
		},
		flush(cb) { if (!done) finish(this); cb() },
	})
}

function matchRoute(pathname) {
	const p = pathname.replace(/^\//, "")
	for (const r of ROUTES) {
		if (p === r.prefix || p.startsWith(r.prefix + "/")) {
			const rest = p.slice(r.prefix.length) // includes leading "/" or ""
			return { route: r, rest }
		}
	}
	return null
}

// Returns { header, value } to inject, or null. Defaults to Authorization: Bearer
// <token>; routes can override authHeader (e.g. context7 uses CONTEXT7_API_KEY)
// and authScheme ("" for a raw token with no "Bearer " prefix).
function resolveAuth(route) {
	if (!route.authEnv) return null
	const token = process.env[route.authEnv]
	if (!token) throw new Error(`missing env ${route.authEnv} for route ${route.prefix}`)
	const header = (route.authHeader || "authorization").toLowerCase()
	const scheme = route.authScheme === undefined ? "Bearer " : route.authScheme
	const value = token.startsWith(scheme) && scheme ? token : `${scheme}${token}`
	return { header, value }
}

const server = http.createServer((req, res) => {
	// Health check (no auth) so launchd / curl can probe liveness.
	if (req.url === "/healthz") {
		res.writeHead(200, { "content-type": "application/json" })
		res.end(
			JSON.stringify({
				ok: true,
				routes: ROUTES.map((r) => r.prefix),
				children: [...children.entries()].map(([key, e]) => ({
					key,
					prefix: e.prefix ?? key,
					accessMode: e.accessMode ?? null,
					port: e.port,
					pid: e.proc?.pid ?? null,
					alive: !!e.proc && e.proc.exitCode === null,
				})),
			}),
		)
		return
	}

	if (LOCAL_TOKEN && req.headers["x-mcp-gateway-token"] !== LOCAL_TOKEN) {
		res.writeHead(401, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: "unauthorized: bad or missing x-mcp-gateway-token" }))
		return
	}

	const url = new URL(req.url, `http://${req.headers.host || HOST}`)
	const matched = matchRoute(url.pathname)
	if (!matched) {
		res.writeHead(404, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: `no route for ${url.pathname}` }))
		return
	}

	const { route, rest } = matched
	let auth
	try {
		auth = resolveAuth(route)
	} catch (e) {
		res.writeHead(502, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: String(e.message || e) }))
		return
	}
	let accessMode = null
	try {
		accessMode = accessModeForRequest(route, url)
	} catch (e) {
		res.writeHead(400, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: String(e.message || e) }))
		return
	}

	const activeSpawn = route.spawn ? ensureSpawnRoute(route, accessMode) : null
	if (route.spawn && !activeSpawn) {
		res.writeHead(502, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: `spawn route unavailable: ${route.prefix} (${accessMode})` }))
		return
	}

	const target = new URL(route.target)
	if (activeSpawn) target.port = String(activeSpawn.port)
	// Append any subpath after the route prefix, then the original query string.
	target.pathname = (target.pathname.replace(/\/$/, "") + rest).replace(/\/+/g, "/") || "/"
	const upstreamSearch = new URLSearchParams(url.searchParams)
	for (const key of ["access_mode", "accessMode", "postgres_access_mode", "postgresAccessMode"]) upstreamSearch.delete(key)
	target.search = upstreamSearch.toString() ? `?${upstreamSearch}` : ""

	// Copy client headers, then override host + auth. Drop hop-by-hop and the
	// local-gateway token so they never leak upstream.
	const headers = { ...req.headers }
	delete headers.host
	delete headers["x-mcp-gateway-token"]
	delete headers.connection
	delete headers["content-length"] // let the agent recompute via streaming
	// Drop any client-supplied credential headers before injecting ours.
	delete headers.authorization
	if (auth) {
		if (auth.header !== "authorization") delete headers[auth.header]
		headers[auth.header] = auth.value
	}
	// Ensure a session id reaches upstream even for clients that send neither the
	// session_id tool arg nor x-session-id (e.g. Codex). Fall back to the MCP
	// transport session so upstream (autodev-memory build_actor) can still record
	// which session produced each ticket/artifact event. Fill-only: never
	// overrides a client-supplied x-session-id.
	if (!headers["x-session-id"] && headers["mcp-session-id"]) {
		headers["x-session-id"] = headers["mcp-session-id"]
	}
	headers.host = target.host

	const agent = target.protocol === "https:" ? httpsAgent : httpAgent
	const transport = target.protocol === "https:" ? https : http

	// Buffer the (small) MCP request body so a first attempt that lands on a dead
	// pooled keep-alive socket can be transparently retried on a fresh one. MCP
	// request bodies are short JSON POSTs (or empty GETs for SSE), so buffering is
	// cheap and lets us send an accurate Content-Length instead of chunked.
	let body = null
	let clientAborted = false
	const bodyChunks = []
	req.on("data", (c) => bodyChunks.push(c))
	req.on("aborted", () => { clientAborted = true })
	req.on("error", () => { clientAborted = true })
	req.on("end", () => {
		if (clientAborted) return
		body = bodyChunks.length ? Buffer.concat(bodyChunks) : null
		// Base64-encode free-text fields of autodev-memory write tool-calls so they slip past
		// Render's edge WAF (decoded by matching middleware server-side). Transparent: a no-op
		// for every other route and any non-write/unparseable body.
		if (body && route.target && route.target.includes("autodev-memory")) {
			body = encodeAutodevWriteBody(body)
		}
		if (body) headers["content-length"] = String(body.length)
		else delete headers["content-length"]
		send(1)
	})

	// attempt 1 reuses the pooled socket with a short time-to-first-byte guard; if
	// that socket is a half-open corpse the guard fires fast and attempt 2 opens a
	// brand-new socket (agent:false) with a longer guard that also tolerates a
	// Render cold start. We only ever retry before any response byte has been
	// relayed, so the client sees exactly one clean response and a side-effecting
	// call is never double-relayed mid-stream.
	function send(attempt) {
		const first = attempt === 1
		let responded = false
		let timer

		const upstream = transport.request(
			target,
			{ method: req.method, headers, agent: first ? agent : false },
			(ures) => {
				responded = true
				clearTimeout(timer)
				res.writeHead(ures.statusCode || 502, ures.headers)
				// For spawned SSE children, rewrite the `endpoint` event so the client's
				// POST comes back through this prefixed route (see sseEndpointRewriter).
				const ct = ures.headers["content-type"] || ""
				if (route.spawn && /text\/event-stream/i.test(ct)) {
					ures.pipe(sseEndpointRewriter("/" + route.prefix, accessMode)).pipe(res)
				} else {
					ures.pipe(res)
				}
			},
		)

		// TCP keepalive probes reap dead direct-origin sockets. (No help when a CDN
		// keeps its edge socket up while the origin behind it is gone — that case is
		// exactly what the time-to-first-byte guard below catches.)
		upstream.on("socket", (s) => s.setKeepAlive(true, 15_000))

		// Guard only the time to response *headers*, then clear it — never time out
		// a healthy long-lived SSE stream that is legitimately idle after headers.
		timer = setTimeout(() => {
			if (!responded) {
				upstream.destroy(Object.assign(new Error("upstream time-to-first-byte timeout"), { code: "ETIMEDOUT" }))
			}
		}, first ? FIRST_BYTE_MS : RETRY_BYTE_MS)

		upstream.on("error", (err) => {
			clearTimeout(timer)
			const code = err.code || ""
			const retryable = RETRYABLE.has(code) || /timeout|socket hang up/i.test(String(err.message))
			const spawnStarting = route.spawn && code === "ECONNREFUSED" && attempt < 10
			if ((first && retryable || spawnStarting) && !res.headersSent && !clientAborted) {
				const nextAttempt = attempt + 1
				const delay = spawnStarting ? Math.min(1000, 100 * 2 ** Math.max(0, attempt - 1)) : 0
				log("upstream retry", route.prefix, accessMode || "", "->", target.host, code || String(err.message), `attempt=${nextAttempt}`, `delay=${delay}ms`)
				setTimeout(() => send(nextAttempt), delay)
				return
			}
			log("upstream error", route.prefix, accessMode || "", "->", target.host, String(err.message || err))
			if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" })
			res.end(JSON.stringify({ error: `upstream error: ${String(err.message || err)}` }))
		})

		// If the client disconnects before the response is fully delivered, tear down the
		// upstream too. For a long-lived SSE stream `responded` is already true (we got
		// headers), so guarding on `responded` would LEAK the upstream — for a spawned
		// postgres-mcp child that strands an SSE session holding a DB connection on every
		// Claude Code restart/window-close. Guard on whether OUR response finished instead;
		// destroying an already-finished request is a harmless no-op for completed calls.
		res.on("close", () => { if (!res.writableFinished) upstream.destroy() })

		if (body) upstream.end(body)
		else upstream.end()
	}
})

server.listen(PORT, HOST, () => {
	log(`mcp-gateway listening on http://${HOST}:${PORT}`)
	log(`routes: ${ROUTES.map((r) => r.prefix).join(", ")}`)
	log(`local auth: ${LOCAL_TOKEN ? "required (x-mcp-gateway-token)" : "off (localhost only)"}`)
	startAllSpawnRoutes()
})

// SIGHUP reloads routes.json without dropping the listener / pooled sockets. For spawn
// routes it is additive: newly-added children are started; already-running children are
// left in place (so a reload never drops live MCP sessions). Removing a spawn route does
// not stop its child until the next daemon restart.
process.on("SIGHUP", () => {
	try {
		ROUTES = loadRoutes()
		const fresh = ROUTES.filter((r) => r.spawn && !children.has(r.prefix))
		if (fresh.length) {
			reapStrayChildren(fresh.map((r) => r.spawn.port))
			for (const r of fresh) startSpawnRoute(r)
		}
		log("reloaded routes:", ROUTES.map((r) => r.prefix).join(", "))
	} catch (e) {
		log("route reload failed:", String(e.message || e))
	}
})

// Kill daemon-owned children on shutdown so launchd unload tears the whole tree down
// (no orphaned postgres-mcp servers — the problem the per-session spawns used to cause).
process.on("SIGTERM", () => shutdown("SIGTERM"))
process.on("SIGINT", () => shutdown("SIGINT"))
