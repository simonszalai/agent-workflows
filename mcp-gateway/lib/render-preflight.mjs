// Render workspace preflight — the one upstream-specific behavior the proxy carries.
//
// The hosted Render MCP scopes "selected workspace" to the MCP session, and the selection
// resets on every new session/reconnect. Every agent's first workspace-requiring call used
// to hit "no workspace set…" and agents kept stopping to ask the user despite starred
// memories saying not to. Each account routed here has exactly ONE workspace, so selection
// can never target an unintended resource. Fix it below the model entirely: on the first
// POST of each MCP session to a render route, the gateway itself issues one
// select_workspace/list_workspaces tools/call upstream, so no client ever observes the
// unselected state.
import http from "node:http"
import https from "node:https"
import { log } from "./log.mjs"

const PREFLIGHT_ID = "mcp-gateway-workspace-preflight"
const preflighted = new Map() // `${prefix}|${mcp-session-id}` -> Promise (pending) | true (done)

export function isRenderRoute(route) {
	return !!route.renderWorkspace || (typeof route.target === "string" && route.target.startsWith("https://mcp.render.com"))
}

function preflight(route, auth, sessionId, agents) {
	// With an explicit renderWorkspace id (routes.json) select it deterministically;
	// otherwise list_workspaces, which auto-selects on single-workspace accounts.
	const body = Buffer.from(JSON.stringify({
		jsonrpc: "2.0",
		id: PREFLIGHT_ID,
		method: "tools/call",
		params: route.renderWorkspace
			? { name: "select_workspace", arguments: { ownerID: route.renderWorkspace } }
			: { name: "list_workspaces", arguments: {} },
	}))
	const target = new URL(route.target)
	const headers = {
		host: target.host,
		"content-type": "application/json",
		accept: "application/json, text/event-stream",
		"mcp-session-id": sessionId,
		"content-length": String(body.length),
	}
	if (auth) headers[auth.header] = auth.value
	const transport = target.protocol === "https:" ? https : http
	const agent = target.protocol === "https:" ? agents.https : agents.http
	return new Promise((resolve, reject) => {
		const upstream = transport.request(target, { method: "POST", headers, agent }, (ures) => {
			const chunks = []
			ures.on("data", (c) => chunks.push(c))
			ures.on("end", () => {
				const text = Buffer.concat(chunks).toString("utf8")
				if ((ures.statusCode || 0) >= 400) reject(new Error(`status ${ures.statusCode}: ${text.slice(0, 200)}`))
				else resolve(text)
			})
			ures.on("error", reject)
		})
		upstream.setTimeout(20_000, () => upstream.destroy(new Error("render preflight time-to-response timeout")))
		upstream.on("error", reject)
		upstream.end(body)
	})
}

// Resolves once the session has a workspace selected; resolves immediately for
// non-render routes, session-less requests (initialize), and non-POSTs. Never
// rejects: a failed preflight is logged and forgotten (the next request retries),
// and the original call proceeds — worst case the client sees the historical
// "no workspace set" error and the skill-level fallback still applies.
export function ensureRenderWorkspace(route, auth, req, body, agents) {
	if (!isRenderRoute(route) || req.method !== "POST") return Promise.resolve()
	const sessionId = req.headers["mcp-session-id"]
	if (!sessionId) return Promise.resolve()
	const key = `${route.prefix}|${sessionId}`
	const state = preflighted.get(key)
	if (state === true) return Promise.resolve()
	if (state) return state
	// The initialize POST of a resumed session has no tools available yet — skip it;
	// the session's first real call (usually notifications/initialized) preflights.
	let method
	try { method = JSON.parse(body.toString("utf8")).method } catch {}
	if (method === "initialize") return Promise.resolve()
	// Bound the map: sessions are short-lived, evict the oldest quarter when full.
	if (preflighted.size >= 1024) {
		for (const k of [...preflighted.keys()].slice(0, 256)) preflighted.delete(k)
	}
	const p = preflight(route, auth, sessionId, agents)
		.then(() => {
			preflighted.set(key, true)
			log(`render workspace preflight ok ${route.prefix} session=…${sessionId.slice(-12)}`)
		})
		.catch((err) => {
			preflighted.delete(key)
			log(`render workspace preflight failed ${route.prefix}: ${String(err.message || err)}`)
		})
	preflighted.set(key, p)
	return p
}
