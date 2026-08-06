#!/usr/bin/env node
// Loopback MCP auth proxy. It supports either one fixed upstream (cloud/Hermes)
// or a static route table (the shared Mac daemon). Route selection happens from
// the checked-in URL prefix, never from model-supplied MCP arguments.
//
// Single-upstream mode:
//   MCP_PROXY_PORT, MCP_PROXY_UPSTREAM, MCP_PROXY_AUTH_ENV
//
// Routed mode:
//   MCP_PROXY_PORT, MCP_PROXY_ROUTES_FILE
//   The route file names auth environment variables but contains no secrets.
//
// Both modes optionally use MCP_PROXY_BODY_TRANSFORM, an ESM module exporting
// encodeAutodevWriteBody(Buffer). In routed mode only routes with
// "transformBody": true use it.
import fs from "node:fs"
import http from "node:http"
import https from "node:https"

const PORT = Number(process.env.MCP_PROXY_PORT)
const LABEL = process.argv[2] || "mcp-proxy"
const ROUTES_FILE = process.env.MCP_PROXY_ROUTES_FILE || ""
const FIXED_PREFIX = process.env.MCP_PROXY_PREFIX || ""
const TRANSFORM_PATH = process.env.MCP_PROXY_BODY_TRANSFORM || ""
const ROUTED_MODE = Boolean(ROUTES_FILE)

function fatal(message) {
	console.error(`[${LABEL}] FATAL: ${message}`)
	process.exit(1)
}

if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) fatal("MCP_PROXY_PORT is invalid")

function normalizePrefix(value) {
	if (typeof value !== "string" || !value.startsWith("/") || value.includes("?") || value.includes("#")) {
		fatal(`invalid route prefix ${JSON.stringify(value)}`)
	}
	if (value.length > 1 && value.endsWith("/")) return value.slice(0, -1)
	return value
}

function loadRouteSpecs() {
	if (!ROUTED_MODE) {
		const upstream = process.env.MCP_PROXY_UPSTREAM
		const authEnv = process.env.MCP_PROXY_AUTH_ENV
		if (!upstream) fatal("MCP_PROXY_UPSTREAM is unset")
		if (!authEnv) fatal("MCP_PROXY_AUTH_ENV is unset")
		return [{
			prefix: FIXED_PREFIX ? normalizePrefix(FIXED_PREFIX) : "/",
			upstream,
			authEnv,
			authOptional: process.env.MCP_PROXY_AUTH_OPTIONAL === "1",
			transformBody: Boolean(TRANSFORM_PATH),
			renderWorkspace: process.env.MCP_PROXY_RENDER_WORKSPACE || "",
			singleUpstream: true,
		}]
	}

	let parsed
	try {
		parsed = JSON.parse(fs.readFileSync(ROUTES_FILE, "utf8"))
	} catch (error) {
		fatal(`cannot read MCP_PROXY_ROUTES_FILE ${ROUTES_FILE}: ${error.message}`)
	}
	if (!parsed || !Array.isArray(parsed.routes) || parsed.routes.length === 0) {
		fatal(`${ROUTES_FILE} must contain a non-empty routes array`)
	}
	const prefixes = new Set()
	return parsed.routes.map((spec, index) => {
		const prefix = normalizePrefix(spec.prefix)
		if (prefix === "/") fatal("routed mode does not permit a default '/' route")
		if (prefixes.has(prefix)) fatal(`duplicate route prefix ${prefix}`)
		prefixes.add(prefix)
		if (typeof spec.upstream !== "string" || !spec.upstream) fatal(`route ${prefix} has no upstream`)
		if (typeof spec.authEnv !== "string" || !/^[A-Z][A-Z0-9_]*$/.test(spec.authEnv)) {
			fatal(`route ${prefix} has invalid authEnv`)
		}
		return {
			prefix,
			upstream: spec.upstream,
			authEnv: spec.authEnv,
			authOptional: spec.authOptional === true,
			transformBody: spec.transformBody === true,
			renderWorkspace: "",
			expectedProject: typeof spec.expectedProject === "string" ? spec.expectedProject : "",
			singleUpstream: false,
			index,
		}
	}).sort((a, b) => b.prefix.length - a.prefix.length)
}

const routeSpecs = loadRouteSpecs()
if (routeSpecs.some((route) => route.transformBody) && !TRANSFORM_PATH) {
	fatal("a route requires transformBody but MCP_PROXY_BODY_TRANSFORM is unset")
}

let sharedTransform = null
if (TRANSFORM_PATH) {
	try {
		const mod = await import(TRANSFORM_PATH)
		sharedTransform = mod.encodeAutodevWriteBody
	} catch (error) {
		fatal(`cannot load MCP_PROXY_BODY_TRANSFORM ${TRANSFORM_PATH}: ${error.message}`)
	}
	if (typeof sharedTransform !== "function") {
		fatal(`${TRANSFORM_PATH} exports no encodeAutodevWriteBody()`)
	}
}

const routes = routeSpecs.map((spec) => {
	let upstream
	try {
		upstream = new URL(spec.upstream)
	} catch (error) {
		fatal(`route ${spec.prefix} has invalid upstream: ${error.message}`)
	}
	if (!["http:", "https:"].includes(upstream.protocol)) fatal(`route ${spec.prefix} upstream must be HTTP(S)`)
	const token = process.env[spec.authEnv] || ""
	if (!token && !spec.authOptional) fatal(`${spec.authEnv} (the token itself) is unset for route ${spec.prefix}`)
	const transport = upstream.protocol === "https:" ? https : http
	return {
		...spec,
		upstream,
		token,
		transport,
		agent: new transport.Agent({ keepAlive: true }),
		retrySecs: upstream.hostname === "127.0.0.1" ? Number(process.env.MCP_PROXY_RETRY_SECS || 90) : 0,
		transformBody: spec.transformBody ? sharedTransform : null,
	}
})

function selectRoute(requestUrl) {
	const incoming = new URL(requestUrl || "/", "http://127.0.0.1")
	if (!ROUTED_MODE) {
		const route = routes[0]
		if (route.prefix === "/") {
			return { route, path: route.upstream.pathname + (route.upstream.search || "") }
		}
		if (incoming.pathname !== route.prefix && !incoming.pathname.startsWith(`${route.prefix}/`)) {
			return null
		}
		const remainder = incoming.pathname.slice(route.prefix.length) || "/"
		const base = route.upstream.pathname === "/" ? "" : route.upstream.pathname.replace(/\/$/, "")
		return { route, path: `${base}${remainder}${incoming.search}` }
	}
	const route = routes.find(({ prefix }) => incoming.pathname === prefix || incoming.pathname.startsWith(`${prefix}/`))
	if (!route) return null
	const remainder = incoming.pathname.slice(route.prefix.length) || "/"
	const base = route.upstream.pathname === "/" ? "" : route.upstream.pathname.replace(/\/$/, "")
	return { route, path: `${base}${remainder}${incoming.search}` }
}

// Render support remains for the generic single-upstream deployment mode.
const PREFLIGHT_ID = "mcp-proxy-workspace-preflight"
const preflighted = new Map()

function renderPreflight(route, sessionId) {
	const body = Buffer.from(JSON.stringify({
		jsonrpc: "2.0",
		id: PREFLIGHT_ID,
		method: "tools/call",
		params: { name: "select_workspace", arguments: { ownerID: route.renderWorkspace } },
	}))
	const headers = {
		host: route.upstream.host,
		"content-type": "application/json",
		accept: "application/json, text/event-stream",
		"mcp-session-id": sessionId,
		authorization: `Bearer ${route.token}`,
		"content-length": String(body.length),
	}
	return new Promise((resolve, reject) => {
		const upstream = route.transport.request(route.upstream, { method: "POST", headers, agent: route.agent }, (response) => {
			const chunks = []
			response.on("data", (chunk) => chunks.push(chunk))
			response.on("end", () => {
				const text = Buffer.concat(chunks).toString("utf8")
				if ((response.statusCode || 0) >= 400) reject(new Error(`status ${response.statusCode}: ${text.slice(0, 200)}`))
				else resolve(text)
			})
			response.on("error", reject)
		})
		upstream.setTimeout(20_000, () => upstream.destroy(new Error("render preflight timeout")))
		upstream.on("error", reject)
		upstream.end(body)
	})
}

function ensureRenderWorkspace(route, req, body) {
	if (!route.renderWorkspace || req.method !== "POST") return Promise.resolve()
	const sessionId = req.headers["mcp-session-id"]
	if (!sessionId) return Promise.resolve()
	const key = `${route.prefix}:${sessionId}`
	const state = preflighted.get(key)
	if (state === true) return Promise.resolve()
	if (state) return state
	let method
	try { method = JSON.parse(body.toString("utf8")).method } catch {}
	if (method === "initialize") return Promise.resolve()
	if (preflighted.size >= 1024) {
		for (const oldKey of [...preflighted.keys()].slice(0, 256)) preflighted.delete(oldKey)
	}
	const pending = renderPreflight(route, sessionId)
		.then(() => {
			preflighted.set(key, true)
			console.log(`[${LABEL}] render workspace preflight ok session=…${sessionId.slice(-12)}`)
		})
		.catch((error) => {
			preflighted.delete(key)
			console.error(`[${LABEL}] render workspace preflight failed: ${String(error.message || error)}`)
		})
	preflighted.set(key, pending)
	return pending
}

function forward(route, upstreamPath, req, res, body, retryDeadline = 0) {
	const headers = { ...req.headers }
	delete headers.host
	delete headers.connection
	delete headers["content-length"]
	delete headers.authorization
	if (route.token) headers.authorization = `Bearer ${route.token}`
	headers.host = route.upstream.host
	if (body !== null) headers["content-length"] = String(body.length)

	const retryable = body !== null && retryDeadline > Date.now() && !res.headersSent
	const retry = (why) => {
		console.error(`[${LABEL}] upstream not ready (${why}), retrying...`)
		setTimeout(() => forward(route, upstreamPath, req, res, body, retryDeadline), 1000)
	}

	const upstream = route.transport.request({
		protocol: route.upstream.protocol,
		host: route.upstream.hostname,
		port: route.upstream.port || (route.upstream.protocol === "https:" ? 443 : 80),
		path: upstreamPath,
		method: req.method,
		headers,
		agent: route.agent,
	}, (response) => {
		if (retryable && (response.statusCode || 0) >= 500) {
			response.resume()
			return retry(`status ${response.statusCode}`)
		}
		res.writeHead(response.statusCode || 502, response.headers)
		response.pipe(res)
	})

	upstream.on("error", (error) => {
		if (retryable && retryDeadline > Date.now()) return retry(error.code || error.message)
		console.error(`[${LABEL}] upstream error: ${error.message}`)
		if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: { message: `${LABEL} upstream: ${error.message}` } }))
	})

	if (body !== null) upstream.end(body)
	else req.pipe(upstream)
}

const server = http.createServer((req, res) => {
	const incoming = new URL(req.url || "/", "http://127.0.0.1")
	if (incoming.pathname === "/.well-known" || incoming.pathname.startsWith("/.well-known/") || incoming.pathname.includes("/.well-known/")) {
		res.writeHead(404, { "content-type": "application/json" })
		return res.end("{}")
	}
	if (req.method === "GET" && !req.headers["mcp-session-id"]) {
		res.writeHead(405, { allow: "POST" })
		return res.end()
	}

	const selected = selectRoute(req.url)
	if (!selected) {
		res.writeHead(404, { "content-type": "application/json" })
		return res.end(JSON.stringify({ error: { message: "unknown MCP proxy route" } }))
	}
	const { route, path } = selected
	const mustBuffer = (route.transformBody || route.renderWorkspace || route.retrySecs) && req.method === "POST"
	if (!mustBuffer) return forward(route, path, req, res, null)

	const chunks = []
	req.on("data", (chunk) => chunks.push(chunk))
	req.on("error", (error) => {
		console.error(`[${LABEL}] request error: ${error.message}`)
		if (!res.headersSent) res.writeHead(400)
		res.end()
	})
	req.on("end", () => {
		const raw = Buffer.concat(chunks)
		let outgoing = raw
		if (route.transformBody) {
			try {
				outgoing = route.transformBody(raw)
			} catch (error) {
				console.error(`[${LABEL}] body transform failed, forwarding unchanged: ${error.message}`)
			}
		}
		const deadline = route.retrySecs ? Date.now() + route.retrySecs * 1000 : 0
		ensureRenderWorkspace(route, req, raw).then(() => forward(route, path, req, res, outgoing, deadline))
	})
})

server.listen(PORT, "127.0.0.1", () => {
	if (ROUTED_MODE) {
		console.log(`[${LABEL}] 127.0.0.1:${PORT} routes=${routes.map((route) => route.prefix).join(",")}`)
	} else {
		console.log(`[${LABEL}] 127.0.0.1:${PORT} -> ${routes[0].upstream.origin}${routes[0].upstream.pathname}`)
	}
})
