#!/usr/bin/env node
// Generic loopback MCP auth proxy — the mcp-gateway's replacement, one process per server.
//
// WHY THIS EXISTS
//   MCP client configs (.mcp.json / .codex/config.toml / .grok/config.toml) can only
//   attach credentials by expanding ${VAR} from the *client's* environment — i.e. by
//   putting the secret into every agent process. This proxy holds the credential
//   instead: it is started under `op run` (service-account token), keeps the key in
//   its own process memory only, and the client connects to a bare loopback URL with
//   no credential at all.
//
//   It also dissolves the MCP registry race that killed gateway-style servers in
//   Conductor cloud: the client builds its tool registry ~2s after SessionStart, and
//   this proxy's only startup work is binding a socket (milliseconds). Everything
//   slow — credential resolution, the remote upstream — sits behind the socket.
//
//   Run identically everywhere: Mac (launchd via start-proxies.sh), Conductor cloud
//   (SessionStart via the project's cloud-mcp.sh), other instances (systemd). Fixed
//   well-known ports make the client config a static URL valid in every environment
//   and every client (Codex and Grok cannot expand ${VAR} in `url`).
//
// LINEAGE
//   Superset of ts-prefect scripts/setup/cloud-mcp-proxy.mjs (kept there as a
//   fallback vendored copy — ts-prefect's cloud-mcp.sh prefers THIS file when the
//   agent-workflows checkout exists). Adds the gateway's render workspace preflight.
//
// USAGE  op run --env-file=proxies.env -- node mcp-proxy.mjs <label>
// ENV    MCP_PROXY_PORT              loopback port to listen on
//        MCP_PROXY_UPSTREAM          full upstream URL (http: or https:)
//        MCP_PROXY_AUTH_ENV          name of the env var holding the bearer token
//        MCP_PROXY_BODY_TRANSFORM    optional ESM module path exporting
//                                    encodeAutodevWriteBody(Buffer) -> Buffer
//        MCP_PROXY_RENDER_WORKSPACE  optional Render owner id; enables the per-MCP-
//                                    session select_workspace preflight so clients
//                                    never observe "no workspace selected"
import http from "node:http"
import https from "node:https"

const PORT = Number(process.env.MCP_PROXY_PORT)
const UPSTREAM = new URL(process.env.MCP_PROXY_UPSTREAM || "http://unset.invalid/")
const AUTH_ENV = process.env.MCP_PROXY_AUTH_ENV || ""
const LABEL = process.argv[2] || "mcp-proxy"
const TOKEN = process.env[AUTH_ENV]
const RENDER_WORKSPACE = process.env.MCP_PROXY_RENDER_WORKSPACE || ""

// Fail loudly at boot rather than 401-ing every call later: supervisors treat a
// listening socket as proof of health, so an unauthenticated proxy must never bind.
for (const [name, val] of [
	["MCP_PROXY_PORT", PORT],
	["MCP_PROXY_UPSTREAM", process.env.MCP_PROXY_UPSTREAM],
	["MCP_PROXY_AUTH_ENV", AUTH_ENV],
	[`${AUTH_ENV} (the token itself)`, TOKEN],
]) {
	if (!val) {
		console.error(`[${LABEL}] FATAL: ${name} is unset`)
		process.exit(1)
	}
}

// Loaded at boot, never per-request: a missing module must stop the proxy binding rather
// than surface later as writes that 403 for no visible reason.
const TRANSFORM_PATH = process.env.MCP_PROXY_BODY_TRANSFORM || ""
let transformBody = null
if (TRANSFORM_PATH) {
	try {
		const mod = await import(TRANSFORM_PATH)
		transformBody = mod.encodeAutodevWriteBody
	} catch (err) {
		console.error(`[${LABEL}] FATAL: cannot load MCP_PROXY_BODY_TRANSFORM ${TRANSFORM_PATH}: ${err.message}`)
		process.exit(1)
	}
	if (typeof transformBody !== "function") {
		console.error(`[${LABEL}] FATAL: ${TRANSFORM_PATH} exports no encodeAutodevWriteBody()`)
		process.exit(1)
	}
}

const isTls = UPSTREAM.protocol === "https:"
const transport = isTls ? https : http
// Reuse upstream connections; MCP is chatty and every tool call is a POST.
const agent = new transport.Agent({ keepAlive: true })

// Loopback upstreams are servers WE spawn (e.g. tailscale-mcp-server via npx), and a
// bound socket does not mean a ready server: a client initialize that lands in the
// boot window gets a connection error or 5xx and the whole session permanently loses
// the server — the exact race this proxy exists to kill (observed 2026-07-28: front
// proxy up at :07.8, client init at :10.9, upstream still warming → "failed").
// So buffered requests to a loopback upstream are RETRIED until the upstream answers,
// up to MCP_PROXY_RETRY_SECS (default 90 — npx cold-download is the worst case).
// Remote upstreams (render, autodev) are already-running services and never retry.
const RETRY_SECS = UPSTREAM.hostname === "127.0.0.1"
	? Number(process.env.MCP_PROXY_RETRY_SECS || 90)
	: 0

// ---- Render workspace preflight (ported from mcp-gateway lib/render-preflight.mjs) ----
// The hosted Render MCP scopes "selected workspace" to the MCP session and resets it on
// every reconnect, so agents' first call used to hit "no workspace set" and they stopped
// to ask despite standing instructions not to. There is exactly ONE workspace per routed
// account, so select it below the model entirely: on the first non-initialize POST of
// each MCP session, issue one select_workspace tools/call upstream before forwarding.
const PREFLIGHT_ID = "mcp-proxy-workspace-preflight"
const preflighted = new Map() // mcp-session-id -> Promise (pending) | true (done)

function renderPreflight(sessionId) {
	const body = Buffer.from(JSON.stringify({
		jsonrpc: "2.0",
		id: PREFLIGHT_ID,
		method: "tools/call",
		params: { name: "select_workspace", arguments: { ownerID: RENDER_WORKSPACE } },
	}))
	const headers = {
		host: UPSTREAM.host,
		"content-type": "application/json",
		accept: "application/json, text/event-stream",
		"mcp-session-id": sessionId,
		authorization: `Bearer ${TOKEN}`,
		"content-length": String(body.length),
	}
	return new Promise((resolve, reject) => {
		const upstream = transport.request(UPSTREAM, { method: "POST", headers, agent }, (ures) => {
			const chunks = []
			ures.on("data", (c) => chunks.push(c))
			ures.on("end", () => {
				const text = Buffer.concat(chunks).toString("utf8")
				if ((ures.statusCode || 0) >= 400) reject(new Error(`status ${ures.statusCode}: ${text.slice(0, 200)}`))
				else resolve(text)
			})
			ures.on("error", reject)
		})
		upstream.setTimeout(20_000, () => upstream.destroy(new Error("render preflight timeout")))
		upstream.on("error", reject)
		upstream.end(body)
	})
}

// Resolves once the session has a workspace selected. Never rejects: a failed preflight
// is logged and forgotten (the next request retries), and the original call proceeds —
// worst case the client sees the historical error and the skill-level fallback applies.
function ensureRenderWorkspace(req, body) {
	if (!RENDER_WORKSPACE || req.method !== "POST") return Promise.resolve()
	const sessionId = req.headers["mcp-session-id"]
	if (!sessionId) return Promise.resolve()
	const state = preflighted.get(sessionId)
	if (state === true) return Promise.resolve()
	if (state) return state
	// The initialize POST of a session has no tools available yet — skip it; the
	// session's first real call (usually notifications/initialized) preflights.
	let method
	try { method = JSON.parse(body.toString("utf8")).method } catch {}
	if (method === "initialize") return Promise.resolve()
	// Bound the map: sessions are short-lived, evict the oldest quarter when full.
	if (preflighted.size >= 1024) {
		for (const k of [...preflighted.keys()].slice(0, 256)) preflighted.delete(k)
	}
	const p = renderPreflight(sessionId)
		.then(() => {
			preflighted.set(sessionId, true)
			console.log(`[${LABEL}] render workspace preflight ok session=…${sessionId.slice(-12)}`)
		})
		.catch((err) => {
			preflighted.delete(sessionId)
			console.error(`[${LABEL}] render workspace preflight failed: ${String(err.message || err)}`)
		})
	preflighted.set(sessionId, p)
	return p
}

// body === null means "stream it through". A Buffer means the request was buffered
// (transform, preflight, and/or loopback retry), so content-length is re-derived
// from the new bytes — and only buffered requests can be retried.
const forward = (req, res, body, retryDeadline = 0) => {
	// Copy client headers, then strip what must not cross the boundary.
	// `authorization` is dropped unconditionally BEFORE injecting ours — a
	// client-supplied credential must never reach upstream, and an empty Bearer
	// would 401 the whole session.
	const headers = { ...req.headers }
	delete headers.host
	delete headers.connection
	delete headers["content-length"] // re-derived by the upstream request
	delete headers.authorization
	headers.authorization = `Bearer ${TOKEN}`
	headers.host = UPSTREAM.host
	if (body !== null) headers["content-length"] = String(body.length)

	const retryable = body !== null && retryDeadline > Date.now() && !res.headersSent
	const retry = (why) => {
		console.error(`[${LABEL}] upstream not ready (${why}), retrying...`)
		setTimeout(() => forward(req, res, body, retryDeadline), 1000)
	}

	const upstream = transport.request(
		{
			protocol: UPSTREAM.protocol,
			host: UPSTREAM.hostname,
			port: UPSTREAM.port || (isTls ? 443 : 80),
			// Ignore the client's path: this proxy fronts exactly one upstream, so
			// whatever it receives belongs there.
			path: UPSTREAM.pathname + (UPSTREAM.search || ""),
			method: req.method,
			headers,
			agent,
		},
		(up) => {
			// A booting loopback upstream can bind and still answer 5xx while it warms
			// up; delivering that to a registering client loses the server for the whole
			// session, so treat it like a connection failure while the deadline allows.
			if (retryable && (up.statusCode || 0) >= 500) {
				up.resume() // drain and discard
				return retry(`status ${up.statusCode}`)
			}
			res.writeHead(up.statusCode || 502, up.headers)
			// Pipe, never buffer: MCP Streamable HTTP replies with SSE for anything
			// long-running, and buffering would stall tool calls until completion.
			up.pipe(res)
		},
	)

	upstream.on("error", (err) => {
		if (retryable && retryDeadline > Date.now()) return retry(err.code || err.message)
		console.error(`[${LABEL}] upstream error: ${err.message}`)
		if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: { message: `${LABEL} upstream: ${err.message}` } }))
	})

	if (body !== null) upstream.end(body)
	else req.pipe(upstream)
}

const server = http.createServer((req, res) => {
	// Only POST bodies are ever buffered, and only when a feature needs the bytes
	// (body transform, render preflight's initialize detection, or loopback retry).
	// Responses are always piped — SSE must stream.
	const mustBuffer = (transformBody || RENDER_WORKSPACE || RETRY_SECS) && req.method === "POST"
	if (!mustBuffer) return forward(req, res, null)

	const chunks = []
	req.on("data", (c) => chunks.push(c))
	req.on("error", (err) => {
		console.error(`[${LABEL}] request error: ${err.message}`)
		if (!res.headersSent) res.writeHead(400)
		res.end()
	})
	req.on("end", () => {
		const raw = Buffer.concat(chunks)
		let out = raw
		if (transformBody) {
			try {
				out = transformBody(raw)
			} catch (err) {
				// The encoder is documented as best-effort and transparent; a shape it
				// does not recognise degrades to an unencoded pass-through rather than
				// dropping the call.
				console.error(`[${LABEL}] body transform failed, forwarding unchanged: ${err.message}`)
			}
		}
		const deadline = RETRY_SECS ? Date.now() + RETRY_SECS * 1000 : 0
		ensureRenderWorkspace(req, raw).then(() => forward(req, res, out, deadline))
	})
})

// Loopback only. The credential lives in this process, so the listener must not be
// reachable from outside the machine under any circumstances.
server.listen(PORT, "127.0.0.1", () => {
	console.log(`[${LABEL}] 127.0.0.1:${PORT} -> ${UPSTREAM.origin}${UPSTREAM.pathname}`)
})
