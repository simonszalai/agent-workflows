// The reverse proxy: a transparent streaming relay of MCP-over-HTTP bytes (POST tool
// calls, GET SSE streams, mcp-session-id headers), unchanged except for swapping the
// client's credential for the route's upstream one. It deliberately does NOT model each
// upstream's session semantics — it just pipes.
import http from "node:http"
import https from "node:https"
import { DEFAULT_CLIENT_TOKEN_ENV, HOST } from "./config.mjs"
import { log } from "./log.mjs"
import { ensureRunning, healthSnapshot } from "./supervisor.mjs"
import { ensureRenderWorkspace, isRenderRoute } from "./render-preflight.mjs"
import {
	inspectAllowlistedRequest,
	MAX_ALLOWLIST_REQUEST_BYTES,
	toolPolicyAudit,
} from "./tool-policy.mjs"
import {
	filterToolsListResponse,
	MAX_ALLOWLIST_RESPONSE_BYTES,
	validateToolsListResponseHeaders,
} from "./tool-filter.mjs"
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
export const DEFAULT_ALLOWLIST_BUFFER_LIMITS = Object.freeze({
	maxActive: 8,
	maxBytes: 8 * 1024 * 1024,
	requestBodyMs: 15_000,
	responseBodyMs: 30_000,
})
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
	if (res.writableEnded) return
	if (res.headersSent) {
		res.destroy()
		return
	}
	if (!res.headersSent) res.writeHead(status, { "content-type": "application/json" })
	res.end(JSON.stringify({ error: message }))
}

function validRuntimeAllowTools(route) {
	if (route.allowTools === undefined) return true
	if (!Array.isArray(route.allowTools) || !route.allowTools.length) return false
	const seen = new Set()
	for (const tool of route.allowTools) {
		if (typeof tool !== "string" || !tool.length || tool.trim() !== tool ||
			seen.has(tool)) return false
		seen.add(tool)
	}
	return true
}

function hasFramedRequestBody(headers) {
	if (headers["transfer-encoding"] !== undefined) return true
	const contentLength = headers["content-length"]
	if (contentLength === undefined) return false
	if (Array.isArray(contentLength)) return true
	const normalized = String(contentLength).trim()
	return !/^\d+$/.test(normalized) || Number(normalized) > 0
}

function createBufferBudget(limits) {
	const pools = new Map()
	return {
		acquire(key) {
			const pool = pools.get(key) || { active: 0, bytes: 0 }
			if (pool.active >= limits.maxActive) return null
			pool.active += 1
			pools.set(key, pool)
			let reserved = 0
			let released = false
			return {
				reserve(bytes) {
					if (released || !Number.isSafeInteger(bytes) || bytes < 0 ||
						pool.bytes + bytes > limits.maxBytes) return false
					pool.bytes += bytes
					reserved += bytes
					return true
				},
				releaseBytes(bytes) {
					if (released || !Number.isSafeInteger(bytes) || bytes <= 0) return
					const amount = Math.min(bytes, reserved)
					reserved -= amount
					pool.bytes -= amount
				},
				release() {
					if (released) return
					released = true
					pool.bytes -= reserved
					pool.active -= 1
					if (!pool.active) pools.delete(key)
				},
			}
		},
	}
}

// getRoutes is a thunk so SIGHUP reloads take effect without re-wiring the server.
export function createRequestHandler(getRoutes, {
	logger = log,
	bufferLimits = DEFAULT_ALLOWLIST_BUFFER_LIMITS,
	ensureRouteRunning = ensureRunning,
} = {}) {
	const limits = { ...DEFAULT_ALLOWLIST_BUFFER_LIMITS, ...bufferLimits }
	const bufferBudget = createBufferBudget(limits)
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

		const url = new URL(req.url, `http://${req.headers.host || HOST}`)
		const routes = getRoutes()
		const matched = matchRoute(routes, url.pathname)
		if (!matched) return jsonError(res, 404, `no route for ${url.pathname}`)

		const { route, rest } = matched
		if (!validRuntimeAllowTools(route)) {
			return jsonError(res, 503, "route disabled: invalid tool policy")
		}
		const clientTokenEnv = route.clientTokenEnv === undefined
			? DEFAULT_CLIENT_TOKEN_ENV
			: route.clientTokenEnv
		if (typeof clientTokenEnv !== "string" ||
			!/^[A-Z_][A-Z0-9_]*$/.test(clientTokenEnv)) {
			return jsonError(res, 503, "route disabled: invalid client credential policy")
		}
		const clientToken = process.env[clientTokenEnv]
		const tokenCollision = clientToken && routes.some((candidate) => {
			const otherEnv = candidate.clientTokenEnv === undefined
				? DEFAULT_CLIENT_TOKEN_ENV
				: candidate.clientTokenEnv
			return typeof otherEnv === "string" &&
				otherEnv !== clientTokenEnv &&
				process.env[otherEnv] === clientToken
		})
		if (tokenCollision) {
			return jsonError(res, 503, "route disabled: client credential collision")
		}
		if (!clientToken && clientTokenEnv !== DEFAULT_CLIENT_TOKEN_ENV) {
			return jsonError(res, 503, "route disabled: client credential unavailable")
		}
		if (clientToken && req.headers["x-mcp-gateway-token"] !== clientToken) {
			return jsonError(res, 401, "unauthorized: bad or missing x-mcp-gateway-token")
		}

		let auth
		try {
			auth = resolveAuth(route)
		} catch (e) {
			if (clientTokenEnv !== DEFAULT_CLIENT_TOKEN_ENV) {
				return jsonError(res, 503, "route disabled: upstream credential unavailable")
			}
			return jsonError(res, 502, String(e.message || e))
		}

		const buffersAllowlistedBody = Array.isArray(route.allowTools) &&
			hasFramedRequestBody(req.headers)
		const bufferLease = buffersAllowlistedBody
			? bufferBudget.acquire(`${route.prefix}\0${clientTokenEnv}`)
			: null
		if (buffersAllowlistedBody && !bufferLease) {
			logger("allowlist buffer denied", JSON.stringify({
				event: "mcp_gateway_allowlist_buffer_denied",
				route: route.prefix,
				reason: "concurrency_limit",
				outcome: "denied",
			}))
			req.resume()
			return jsonError(res, 429, "route buffer capacity exhausted")
		}
		bufferLease && res.once("finish", () => bufferLease.release())
		bufferLease && res.once("close", () => bufferLease.release())

		if (route.spawn && !ensureRouteRunning(route)) {
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
		// pooled keep-alive socket can be transparently retried on a fresh one. Every
		// allowlisted method is budgeted while buffering; bodyless GET/SSE requests
		// remain byte-transparent and release their lease before response streaming.
		let body = null
		let clientAborted = false
		let policyRejected = false
		let bodyBytes = 0
		let requestReservedBytes = 0
		const bodyChunks = []
		let requestBodyTimer
		const denyPolicy = (
			reason,
			toolName,
			status = 403,
			message = "request denied by route tool policy",
		) => {
			if (policyRejected) return
			policyRejected = true
			clearTimeout(requestBodyTimer)
			body = null
			bodyChunks.length = 0
			logger("tool policy denied", JSON.stringify(toolPolicyAudit(route, reason, toolName)))
			bufferLease?.release()
			req.resume()
			jsonError(res, status, message)
		}
		if (bufferLease) {
			requestBodyTimer = setTimeout(() => {
				denyPolicy(
					"request_body_timeout",
					undefined,
					408,
					"allowlisted request body deadline exceeded",
				)
			}, limits.requestBodyMs)
			requestBodyTimer.unref?.()
		}
		req.on("data", (c) => {
			if (policyRejected) return
			bodyBytes += c.length
			if (Array.isArray(route.allowTools) &&
				bodyBytes > MAX_ALLOWLIST_REQUEST_BYTES) {
				denyPolicy("request_too_large")
				return
			}
			if (bufferLease && !bufferLease.reserve(c.length)) {
				denyPolicy(
					"aggregate_buffer_limit",
					undefined,
					429,
					"route buffer capacity exhausted",
				)
				return
			}
			requestReservedBytes += c.length
			bodyChunks.push(c)
		})
		req.on("aborted", () => {
			clientAborted = true
			clearTimeout(requestBodyTimer)
			body = null
			bodyChunks.length = 0
			bufferLease?.release()
		})
		req.on("error", () => {
			clientAborted = true
			clearTimeout(requestBodyTimer)
			body = null
			bodyChunks.length = 0
			bufferLease?.release()
		})
		req.on("end", () => {
			clearTimeout(requestBodyTimer)
			if (clientAborted || policyRejected) return
			body = bodyChunks.length ? Buffer.concat(bodyChunks) : null
			bodyChunks.length = 0
			const decision = inspectAllowlistedRequest({
				method: req.method,
				headers: req.headers,
				body,
				allowTools: route.allowTools,
			})
			if (!decision.allowed) {
				denyPolicy(decision.reason, decision.toolName)
				return
			}
			const filterToolsList = decision.isToolsList
			// Base64-encode free-text fields of autodev-memory write tool-calls so they slip
			// past Render's edge WAF (decoded by matching middleware server-side). A no-op
			// for every other route and any non-write/unparseable body.
			if (body && route.target && route.target.includes("autodev-memory")) {
				const originalLength = body.length
				body = encodeAutodevWriteBody(body)
				const sizeDelta = body.length - originalLength
				if (sizeDelta > 0 && bufferLease && !bufferLease.reserve(sizeDelta)) {
					denyPolicy(
						"aggregate_buffer_limit",
						undefined,
						429,
						"route buffer capacity exhausted",
					)
					return
				}
				if (sizeDelta < 0) bufferLease?.releaseBytes(-sizeDelta)
				requestReservedBytes += sizeDelta
			}
			if (body) headers["content-length"] = String(body.length)
			else delete headers["content-length"]
			// Render routes: make sure the session has its (single) workspace selected
			// before relaying the call. No-op elsewhere.
			if (body && isRenderRoute(route)) {
				ensureRenderWorkspace(route, auth, req, body, agents).then(() => {
					if (!clientAborted) send(1, filterToolsList)
				})
			} else {
				send(1, filterToolsList)
			}
		})

		// Attempt 1 reuses the pooled socket with a short time-to-first-byte guard; if
		// that socket is a half-open corpse the guard fires fast and attempt 2 opens a
		// brand-new socket (agent:false) with a longer guard that also tolerates a Render
		// cold start. We only ever retry before any response byte has been relayed, so
		// the client sees exactly one clean response and a side-effecting call is never
		// double-relayed mid-stream.
		function send(attempt, filterToolsList) {
			const first = attempt === 1
			let responded = false
			let timer

			const upstream = transport.request(
				target,
				{ method: req.method, headers, agent: first ? agent : false },
				(ures) => {
					responded = true
					clearTimeout(timer)
					if (bufferLease) {
						body = null
						bufferLease.releaseBytes(requestReservedBytes)
						requestReservedBytes = 0
					}
					if (!filterToolsList) {
						bufferLease?.release()
						res.writeHead(ures.statusCode || 502, ures.headers)
						ures.pipe(res)
						return
					}

					let finished = false
					let bytes = 0
					const chunks = []
					let responseBodyTimer
					const denyResponse = (reason) => {
						if (finished) return
						finished = true
						clearTimeout(responseBodyTimer)
						chunks.length = 0
						logger("tool list filter denied", JSON.stringify({
							event: "mcp_gateway_tool_list_filter_denied",
							route: route.prefix,
							reason,
							outcome: "denied",
						}))
						bufferLease?.release()
						jsonError(res, 403, "upstream tools/list response denied")
						ures.destroy()
					}
					try {
						validateToolsListResponseHeaders(ures.headers)
					} catch (error) {
						denyResponse(error.reason || "unsupported_response_headers")
						return
					}
					if (bufferLease) {
						responseBodyTimer = setTimeout(
							() => denyResponse("response_body_timeout"),
							limits.responseBodyMs,
						)
						responseBodyTimer.unref?.()
					}
					ures.on("data", (chunk) => {
						if (finished) return
						bytes += chunk.length
						if (bytes > MAX_ALLOWLIST_RESPONSE_BYTES) {
							denyResponse("response_too_large")
							return
						}
						if (bufferLease && !bufferLease.reserve(chunk.length)) {
							denyResponse("aggregate_buffer_limit")
							return
						}
						chunks.push(chunk)
					})
					ures.on("aborted", () => denyResponse("upstream_aborted"))
					ures.on("error", () => denyResponse("upstream_error"))
					ures.on("end", () => {
						if (finished) return
						clearTimeout(responseBodyTimer)
						try {
							const filtered = filterToolsListResponse(
								Buffer.concat(chunks),
								ures.headers,
								route.allowTools,
							)
							chunks.length = 0
							finished = true
							res.writeHead(ures.statusCode || 502, filtered.headers)
							res.end(filtered.body)
						} catch (error) {
							denyResponse(error.reason || "unsupported_response")
						}
					})
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
				if ((first && retryable || spawnStarting) && !responded &&
					!res.headersSent && !clientAborted) {
					const nextAttempt = attempt + 1
					const delay = spawnStarting ? Math.min(1000, 100 * 2 ** Math.max(0, attempt - 1)) : 0
					log("upstream retry", route.prefix, "->", target.host, code || String(err.message), `attempt=${nextAttempt}`, `delay=${delay}ms`)
					setTimeout(() => send(nextAttempt, filterToolsList), delay)
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
