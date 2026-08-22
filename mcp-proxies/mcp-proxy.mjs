#!/usr/bin/env node
// Fixed-upstream loopback MCP auth proxy for the Hermes system service.
// Interactive coding clients use per-session stdio bridges instead.
import http from "node:http"
import https from "node:https"

const PORT = Number(process.env.MCP_PROXY_PORT)
const LABEL = process.argv[2] || "mcp-proxy"
const UPSTREAM_RAW = process.env.MCP_PROXY_UPSTREAM || ""
const AUTH_ENV = process.env.MCP_PROXY_AUTH_ENV || ""
const TRANSFORM_PATH = process.env.MCP_PROXY_BODY_TRANSFORM || ""

function fatal(message) {
	console.error(`[${LABEL}] FATAL: ${message}`)
	process.exit(1)
}

if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) fatal("MCP_PROXY_PORT is invalid")
if (!UPSTREAM_RAW) fatal("MCP_PROXY_UPSTREAM is unset")
if (!/^[A-Z][A-Z0-9_]*$/.test(AUTH_ENV)) fatal("MCP_PROXY_AUTH_ENV is invalid")

let upstream
try {
	upstream = new URL(UPSTREAM_RAW)
} catch (error) {
	fatal(`MCP_PROXY_UPSTREAM is invalid: ${error.message}`)
}
if (!["http:", "https:"].includes(upstream.protocol)) fatal("MCP_PROXY_UPSTREAM must be HTTP(S)")

const token = process.env[AUTH_ENV] || ""
if (!token) fatal(`${AUTH_ENV} is unset`)

let transform = null
if (TRANSFORM_PATH) {
	try {
		const module = await import(TRANSFORM_PATH)
		transform = module.encodeAutodevWriteBody
	} catch (error) {
		fatal(`cannot load MCP_PROXY_BODY_TRANSFORM ${TRANSFORM_PATH}: ${error.message}`)
	}
	if (typeof transform !== "function") {
		fatal(`${TRANSFORM_PATH} exports no encodeAutodevWriteBody()`)
	}
}

const transport = upstream.protocol === "https:" ? https : http
const agent = new transport.Agent({ keepAlive: true })

function forward(req, res, body) {
	const headers = { ...req.headers }
	delete headers.host
	delete headers.connection
	delete headers["content-length"]
	delete headers.authorization
	headers.authorization = `Bearer ${token}`
	headers.host = upstream.host
	if (body !== null) headers["content-length"] = String(body.length)

	const request = transport.request({
		protocol: upstream.protocol,
		host: upstream.hostname,
		port: upstream.port || (upstream.protocol === "https:" ? 443 : 80),
		path: upstream.pathname + upstream.search,
		method: req.method,
		headers,
		agent,
	}, (response) => {
		res.writeHead(response.statusCode || 502, response.headers)
		response.pipe(res)
	})
	request.on("error", (error) => {
		console.error(`[${LABEL}] upstream error: ${error.message}`)
		if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" })
		res.end(JSON.stringify({ error: { message: `${LABEL} upstream unavailable` } }))
	})
	if (body !== null) request.end(body)
	else req.pipe(request)
}

const server = http.createServer((req, res) => {
	const incoming = new URL(req.url || "/", "http://127.0.0.1")
	if (incoming.pathname === "/.well-known" || incoming.pathname.startsWith("/.well-known/")) {
		res.writeHead(404, { "content-type": "application/json" })
		return res.end("{}")
	}
	if (req.method === "GET" && !req.headers["mcp-session-id"]) {
		res.writeHead(405, { allow: "POST" })
		return res.end()
	}
	if (!transform || req.method !== "POST") return forward(req, res, null)

	const chunks = []
	req.on("data", (chunk) => chunks.push(chunk))
	req.on("error", (error) => {
		console.error(`[${LABEL}] request error: ${error.message}`)
		if (!res.headersSent) res.writeHead(400)
		res.end()
	})
	req.on("end", () => {
		const raw = Buffer.concat(chunks)
		let body = raw
		try {
			body = transform(raw)
		} catch (error) {
			console.error(`[${LABEL}] body transform failed, forwarding unchanged: ${error.message}`)
		}
		forward(req, res, body)
	})
})

server.listen(PORT, "127.0.0.1", () => {
	console.log(`[${LABEL}] 127.0.0.1:${PORT} -> ${upstream.origin}${upstream.pathname}`)
})
