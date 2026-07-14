// The reverse proxy: a transparent streaming relay of MCP-over-HTTP bytes (POST tool
// calls, GET SSE streams, mcp-session-id headers), unchanged except for swapping the
// client's credential for the route's upstream one. It deliberately does NOT model each
// upstream's session semantics — it just pipes.
import http from "node:http"
import https from "node:https"
import { LOCAL_TOKEN, HOST } from "./config.mjs"
import { log } from "./log.mjs"
import { ensureRunning, healthSnapshot } from "./supervisor.mjs"
import { ensureRenderWorkspace, isRenderRoute } from "./render-preflight.mjs"
import { encodeAutodevWriteBody } from "../waf-encode.mjs"

// One pooled agent per protocol, shared across ALL routes and sessions: bounded
// keep-alive sockets to each upstream host instead of one fresh client per workspace.
// maxFreeSockets stays small so stale/half-open sockets can't pile up when an upstream
// (e.g. a Render instance) is recycled.
export const agents = {
	https: new https.Agent({ keepAlive: true, maxSockets: 32, maxFreeSockets: 8, keepAliveMsecs: 30_000 }),
	http: new http.Agent({ keepAlive: true, maxSockets: 32, maxFreeSockets: 8, keepAliveMsecs: 30_000 }),
}

// Time-to-first-byte guards. A pooled keep-alive socket whose peer was silently torn
// down (Render idle-spindown / instance recycle behind Cloudflare, where TCP keepalive
// can't detect the dead origin) black-holes our write: the request would otherwise hang
// until OS TCP retransmit exhaustion (minutes). Attempt 1 uses a short guard so we fail
// fast and retry; the retry opens a fresh socket and uses a longer guard that also
// tolerates a genuine cold start.
const FIRST_BYTE_MS = Number(process.env.MCP_GATEWAY_FIRST_BYTE_MS || 10_000)
const RETRY_BYTE_MS = Number(process.env.MCP_GATEWAY_RETRY_BYTE_MS || 45_000)
// Connection-level failures that are safe to retry on a fresh socket (only ever before
// any response byte has been relayed to the client).
const RETRYABLE = new Set(["ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "EPIPE", "ECONNABORTED", "EHOSTUNREACH", "ENETUNREACH"])

function matchRoute(routes, pathname) {
	const p = pathname.replace(/^\//, "")
	for (const r of routes) {
		if (p === r.prefix || p.startsWith(r.prefix + "/")) {
			return { route: r, rest: p.slice(r.prefix.length) } // rest includes leading "/" or ""
		}
	}
	return null
}

// Returns { header, value } to inject, or null. Defaults to Authorization: Bearer
// <token>; routes can override authHeader (e.g. context7 uses CONTEXT7_API_KEY) and
// authScheme ("" for a raw token with no "Bearer " prefix).
function resolveAuth(route) {
	if (!route.authEnv) return null
	const token = process.env[route.authEnv]
	if (!token) throw new Error(`missing env ${route.authEnv} for route ${route.prefix}`)
	const header = (route.authHeader || "authorization").toLowerCase()
	const scheme = route.authScheme === undefined ? "Bearer " : route.authScheme
	const value = token.startsWith(scheme) && scheme ? token : `${scheme}${token}`
	return { header, value }
}

function jsonError(res, status, message) {
	if (!res.headersSent) res.writeHead(status, { "content-type": "application/json" })
	res.end(JSON.stringify({ error: message }))
}

// getRoutes is a thunk so SIGHUP reloads take effect without re-wiring the server.
export function createRequestHandler(getRoutes) {
	return (req, res) => {
		// Health check (no auth) so launchd / curl can probe liveness.
		if (req.url === "/healthz") {
			res.writeHead(200, { "content-type": "application/json" })
			res.end(JSON.stringify({
				ok: true,
				routes: getRoutes().map((r) => r.prefix),
				children: healthSnapshot(),
			}))
			return
		}

		if (LOCAL_TOKEN && req.headers["x-mcp-gateway-token"] !== LOCAL_TOKEN) {
			return jsonError(res, 401, "unauthorized: bad or missing x-mcp-gateway-token")
		}

		const url = new URL(req.url, `http://${req.headers.host || HOST}`)
		const matched = matchRoute(getRoutes(), url.pathname)
		if (!matched) return jsonError(res, 404, `no route for ${url.pathname}`)

		const { route, rest } = matched
		let auth
		try {
			auth = resolveAuth(route)
		} catch (e) {
			return jsonError(res, 502, String(e.message || e))
		}

		if (route.spawn && !ensureRunning(route)) {
			return jsonError(res, 502, `spawn route unavailable: ${route.prefix}`)
		}

		const target = new URL(route.target)
		// Append any subpath after the route prefix, then the original query string.
		target.pathname = (target.pathname.replace(/\/$/, "") + rest).replace(/\/+/g, "/") || "/"
		target.search = url.search

		// Copy client headers, then override host + auth. Drop hop-by-hop and the
		// local-gateway token so they never leak upstream.
		const headers = { ...req.headers }
		delete headers.host
		delete headers["x-mcp-gateway-token"]
		delete headers.connection
		delete headers["content-length"] // recomputed after body buffering
		// Drop any client-supplied credential headers before injecting ours.
		delete headers.authorization
		if (auth) {
			if (auth.header !== "authorization") delete headers[auth.header]
			headers[auth.header] = auth.value
		}
		// Ensure a session id reaches upstream even for clients that send neither the
		// session_id tool arg nor x-session-id (e.g. Codex), so upstream (autodev-memory
		// build_actor) can attribute events. Fill-only: never overrides a client value.
		if (!headers["x-session-id"] && headers["mcp-session-id"]) {
			headers["x-session-id"] = headers["mcp-session-id"]
		}
		headers.host = target.host

		const agent = target.protocol === "https:" ? agents.https : agents.http
		const transport = target.protocol === "https:" ? https : http

		// Buffer the (small) MCP request body so a first attempt that lands on a dead
		// pooled keep-alive socket can be transparently retried on a fresh one. MCP
		// request bodies are short JSON POSTs (or empty GETs for SSE), so buffering is
		// cheap and gives an accurate Content-Length.
		let body = null
		let clientAborted = false
		const bodyChunks = []
		req.on("data", (c) => bodyChunks.push(c))
		req.on("aborted", () => { clientAborted = true })
		req.on("error", () => { clientAborted = true })
		req.on("end", () => {
			if (clientAborted) return
			body = bodyChunks.length ? Buffer.concat(bodyChunks) : null
			// Base64-encode free-text fields of autodev-memory write tool-calls so they slip
			// past Render's edge WAF (decoded by matching middleware server-side). A no-op
			// for every other route and any non-write/unparseable body.
			if (body && route.target && route.target.includes("autodev-memory")) {
				body = encodeAutodevWriteBody(body)
			}
			if (body) headers["content-length"] = String(body.length)
			else delete headers["content-length"]
			// Render routes: make sure the session has its (single) workspace selected
			// before relaying the call. No-op elsewhere.
			if (body && isRenderRoute(route)) {
				ensureRenderWorkspace(route, auth, req, body, agents).then(() => { if (!clientAborted) send(1) })
			} else {
				send(1)
			}
		})

		// Attempt 1 reuses the pooled socket with a short time-to-first-byte guard; if
		// that socket is a half-open corpse the guard fires fast and attempt 2 opens a
		// brand-new socket (agent:false) with a longer guard that also tolerates a Render
		// cold start. We only ever retry before any response byte has been relayed, so
		// the client sees exactly one clean response and a side-effecting call is never
		// double-relayed mid-stream.
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
					ures.pipe(res)
				},
			)

			// TCP keepalive probes reap dead direct-origin sockets. (No help when a CDN
			// keeps its edge socket up while the origin behind it is gone — that case is
			// exactly what the time-to-first-byte guard catches.)
			upstream.on("socket", (s) => s.setKeepAlive(true, 15_000))

			// Guard only the time to response *headers*, then clear it — never time out a
			// healthy long-lived SSE stream that is legitimately idle after headers.
			timer = setTimeout(() => {
				if (!responded) {
					upstream.destroy(Object.assign(new Error("upstream time-to-first-byte timeout"), { code: "ETIMEDOUT" }))
				}
			}, first ? FIRST_BYTE_MS : RETRY_BYTE_MS)

			upstream.on("error", (err) => {
				clearTimeout(timer)
				const code = err.code || ""
				const retryable = RETRYABLE.has(code) || /timeout|socket hang up/i.test(String(err.message))
				// A freshly-(re)started child needs a moment to bind; retry ECONNREFUSED
				// with a short backoff instead of failing the client call.
				const spawnStarting = route.spawn && code === "ECONNREFUSED" && attempt < 10
				if ((first && retryable || spawnStarting) && !res.headersSent && !clientAborted) {
					const nextAttempt = attempt + 1
					const delay = spawnStarting ? Math.min(1000, 100 * 2 ** Math.max(0, attempt - 1)) : 0
					log("upstream retry", route.prefix, "->", target.host, code || String(err.message), `attempt=${nextAttempt}`, `delay=${delay}ms`)
					setTimeout(() => send(nextAttempt), delay)
					return
				}
				log("upstream error", route.prefix, "->", target.host, String(err.message || err))
				jsonError(res, 502, `upstream error: ${String(err.message || err)}`)
			})

			// If the client disconnects before the response is fully delivered, tear down
			// the upstream too. For a long-lived SSE stream `responded` is already true (we
			// got headers), so guarding on `responded` would LEAK the upstream. Guard on
			// whether OUR response finished instead; destroying an already-finished request
			// is a harmless no-op for completed calls.
			res.on("close", () => { if (!res.writableFinished) upstream.destroy() })

			if (body) upstream.end(body)
			else upstream.end()
		}
	}
}
