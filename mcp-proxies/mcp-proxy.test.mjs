import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import http from "node:http"
import net from "node:net"
import test from "node:test"

const proxyPath = new URL("./mcp-proxy.mjs", import.meta.url).pathname
const transformPath = new URL("./waf-encode.mjs", import.meta.url).href

async function freePort() {
	const server = net.createServer()
	await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve))
	const { port } = server.address()
	await new Promise((resolve) => server.close(resolve))
	return port
}

async function waitForPort(port, child) {
	for (let attempt = 0; attempt < 80; attempt += 1) {
		if (child.exitCode !== null) throw new Error(`proxy exited with ${child.exitCode}`)
		try {
			await new Promise((resolve, reject) => {
				const socket = net.connect(port, "127.0.0.1", () => {
					socket.end()
					resolve()
				})
				socket.once("error", reject)
			})
			return
		} catch {
			await new Promise((resolve) => setTimeout(resolve, 25))
		}
	}
	throw new Error(`proxy did not listen on ${port}`)
}

async function stop(child) {
	if (child.exitCode !== null) return
	child.kill("SIGTERM")
	await new Promise((resolve) => child.once("exit", resolve))
}

async function startUpstream() {
	const requests = []
	const server = http.createServer((req, res) => {
		const chunks = []
		req.on("data", (chunk) => chunks.push(chunk))
		req.on("end", () => {
			requests.push({
				url: req.url,
				authorization: req.headers.authorization,
				body: Buffer.concat(chunks).toString("utf8"),
			})
			res.writeHead(200, { "content-type": "application/json" })
			res.end(JSON.stringify({ ok: true }))
		})
	})
	await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve))
	return { server, requests, port: server.address().port }
}

test("fixed proxy replaces client auth, fixes the upstream path, and encodes writes", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const child = spawn(process.execPath, [proxyPath, "test-fixed"], {
		env: {
			...process.env,
			MCP_PROXY_PORT: String(proxyPort),
			MCP_PROXY_UPSTREAM: `http://127.0.0.1:${upstream.port}/mcp`,
			MCP_PROXY_AUTH_ENV: "TEST_TOKEN",
			MCP_PROXY_BODY_TRANSFORM: transformPath,
			TEST_TOKEN: "server-secret",
		},
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	const response = await fetch(`http://127.0.0.1:${proxyPort}/ignored/client/path`, {
		method: "POST",
		headers: { authorization: "Bearer client-secret", "content-type": "application/json" },
		body: JSON.stringify({
			jsonrpc: "2.0",
			id: 1,
			method: "tools/call",
			params: { name: "create_memory", arguments: { content: "hello" } },
		}),
	})
	assert.equal(response.status, 200)
	assert.equal(upstream.requests[0].url, "/mcp")
	assert.equal(upstream.requests[0].authorization, "Bearer server-secret")
	assert.match(JSON.parse(upstream.requests[0].body).params.arguments.content, /^@@B64@@/)
})

test("fixed proxy blocks OAuth discovery probes", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const child = spawn(process.execPath, [proxyPath, "test-discovery"], {
		env: {
			...process.env,
			MCP_PROXY_PORT: String(proxyPort),
			MCP_PROXY_UPSTREAM: `http://127.0.0.1:${upstream.port}/mcp`,
			MCP_PROXY_AUTH_ENV: "TEST_TOKEN",
			TEST_TOKEN: "server-secret",
		},
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	const response = await fetch(`http://127.0.0.1:${proxyPort}/.well-known/oauth-authorization-server`)
	assert.equal(response.status, 404)
	assert.equal(upstream.requests.length, 0)
})
