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

const __dirname = dirname(fileURLToPath(import.meta.url))

const HOST = process.env.MCP_GATEWAY_HOST || "127.0.0.1"
const PORT = Number(process.env.MCP_GATEWAY_PORT || 8765)
// Optional shared secret so only configured clients (which send the same header)
// can use the daemon's upstream credentials. Empty = no local auth (localhost only).
const LOCAL_TOKEN = process.env.MCP_GATEWAY_TOKEN || ""

// One pooled agent per protocol, shared across ALL routes and sessions. This is
// the connection pooling: bounded keep-alive sockets to each upstream host
// instead of one fresh client per workspace.
const httpsAgent = new https.Agent({ keepAlive: true, maxSockets: 32, keepAliveMsecs: 30_000 })
const httpAgent = new http.Agent({ keepAlive: true, maxSockets: 32, keepAliveMsecs: 30_000 })

function loadRoutes() {
	const raw = JSON.parse(readFileSync(join(__dirname, "routes.json"), "utf8"))
	// Sort prefixes longest-first so "/ts/postgres_prod_prefect" wins over "/ts".
	return Object.entries(raw.routes)
		.map(([prefix, def]) => ({ prefix: prefix.replace(/^\/|\/$/g, ""), ...def }))
		.sort((a, b) => b.prefix.length - a.prefix.length)
}

let ROUTES = loadRoutes()

function log(...args) {
	console.log(new Date().toISOString(), ...args)
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
		res.end(JSON.stringify({ ok: true, routes: ROUTES.map((r) => r.prefix) }))
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
	delete headers["content-length"] // let the agent recompute via streaming
	// Drop any client-supplied credential headers before injecting ours.
	delete headers.authorization
	if (auth) {
		if (auth.header !== "authorization") delete headers[auth.header]
		headers[auth.header] = auth.value
	}
	headers.host = target.host

	const agent = target.protocol === "https:" ? httpsAgent : httpAgent
	const transport = target.protocol === "https:" ? https : http

	const upstream = transport.request(
		target,
		{ method: req.method, headers, agent },
		(ures) => {
			res.writeHead(ures.statusCode || 502, ures.headers)
			ures.pipe(res)
		},
	)

	upstream.on("error", (err) => {
		log("upstream error", route.prefix, "->", target.host, String(err.message || err))
		if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: `upstream error: ${String(err.message || err)}` }))
	})

	req.pipe(upstream)
})

server.listen(PORT, HOST, () => {
	log(`mcp-gateway listening on http://${HOST}:${PORT}`)
	log(`routes: ${ROUTES.map((r) => r.prefix).join(", ")}`)
	log(`local auth: ${LOCAL_TOKEN ? "required (x-mcp-gateway-token)" : "off (localhost only)"}`)
})

// SIGHUP reloads routes.json without dropping the listener / pooled sockets.
process.on("SIGHUP", () => {
	try {
		ROUTES = loadRoutes()
		log("reloaded routes:", ROUTES.map((r) => r.prefix).join(", "))
	} catch (e) {
		log("route reload failed:", String(e.message || e))
	}
})
