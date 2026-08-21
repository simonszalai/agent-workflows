import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import fs from "node:fs/promises"
import http from "node:http"
import net from "node:net"
import os from "node:os"
import path from "node:path"
import test from "node:test"

const proxyPath = new URL("./mcp-proxy.mjs", import.meta.url).pathname

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

test("routed mode selects bearer from the checked-in URL prefix", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "mcp-proxy-routes-"))
	t.after(() => fs.rm(tempDir, { recursive: true, force: true }))
	const routesFile = path.join(tempDir, "routes.json")
	await fs.writeFile(routesFile, JSON.stringify({ routes: [
		{ prefix: "/amaru", upstream: `http://127.0.0.1:${upstream.port}`, authEnv: "AMARU_TOKEN" },
		{ prefix: "/ts", upstream: `http://127.0.0.1:${upstream.port}`, authEnv: "TS_TOKEN" },
	] }))
	const child = spawn(process.execPath, [proxyPath, "test-router"], {
		env: {
			...process.env,
			MCP_PROXY_PORT: String(proxyPort),
			MCP_PROXY_ROUTES_FILE: routesFile,
			MCP_PROXY_RETRY_SECS: "0",
			AMARU_TOKEN: "amaru-secret",
			TS_TOKEN: "ts-secret",
		},
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	let response = await fetch(`http://127.0.0.1:${proxyPort}/amaru/mcp?test=1`, {
		method: "POST",
		headers: { authorization: "Bearer client-must-not-pass", "content-type": "application/json" },
		body: JSON.stringify({ project: "ts" }),
	})
	assert.equal(response.status, 200)
	response = await fetch(`http://127.0.0.1:${proxyPort}/ts/session-init`, {
		method: "POST",
		body: "{}",
	})
	assert.equal(response.status, 200)

	assert.deepEqual(upstream.requests.map(({ url, authorization }) => ({ url, authorization })), [
		{ url: "/mcp?test=1", authorization: "Bearer amaru-secret" },
		{ url: "/session-init", authorization: "Bearer ts-secret" },
	])
	assert.equal(JSON.parse(upstream.requests[0].body).project, "ts", "server-side restricted bearer owns pinning")
})

test("routed mode skips routes whose auth env is unset and still serves the rest", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "mcp-proxy-routes-"))
	t.after(() => fs.rm(tempDir, { recursive: true, force: true }))
	const routesFile = path.join(tempDir, "routes.json")
	await fs.writeFile(routesFile, JSON.stringify({ routes: [
		{ prefix: "/autodev", upstream: `http://127.0.0.1:${upstream.port}`, authEnv: "AUTODEV_TOKEN" },
		{ prefix: "/ts", upstream: `http://127.0.0.1:${upstream.port}`, authEnv: "TS_TOKEN" },
	] }))
	const child = spawn(process.execPath, [proxyPath, "test-skip-unset"], {
		env: {
			...process.env,
			MCP_PROXY_PORT: String(proxyPort),
			MCP_PROXY_ROUTES_FILE: routesFile,
			MCP_PROXY_RETRY_SECS: "0",
			AUTODEV_TOKEN: "",
			TS_TOKEN: "ts-secret",
		},
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	let response = await fetch(`http://127.0.0.1:${proxyPort}/ts/mcp`, {
		method: "POST",
		body: "{}",
	})
	assert.equal(response.status, 200)
	response = await fetch(`http://127.0.0.1:${proxyPort}/autodev/mcp`, {
		method: "POST",
		body: "{}",
	})
	assert.equal(response.status, 404)
	assert.deepEqual(upstream.requests.map(({ url, authorization }) => ({ url, authorization })), [
		{ url: "/mcp", authorization: "Bearer ts-secret" },
	])
})

test("routed mode has no default route and blocks discovery probes", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "mcp-proxy-routes-"))
	t.after(() => fs.rm(tempDir, { recursive: true, force: true }))
	const routesFile = path.join(tempDir, "routes.json")
	await fs.writeFile(routesFile, JSON.stringify({ routes: [
		{ prefix: "/amaru", upstream: `http://127.0.0.1:${upstream.port}`, authEnv: "AMARU_TOKEN" },
	] }))
	const child = spawn(process.execPath, [proxyPath, "test-router"], {
		env: { ...process.env, MCP_PROXY_PORT: String(proxyPort), MCP_PROXY_ROUTES_FILE: routesFile, AMARU_TOKEN: "secret" },
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	let response = await fetch(`http://127.0.0.1:${proxyPort}/mcp`, { method: "POST", body: "{}" })
	assert.equal(response.status, 404)
	response = await fetch(`http://127.0.0.1:${proxyPort}/amaru/.well-known/oauth-authorization-server`)
	assert.equal(response.status, 404)
	assert.equal(upstream.requests.length, 0)
})

test("single-upstream mode retains fixed upstream behavior", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const child = spawn(process.execPath, [proxyPath, "test-single"], {
		env: {
			...process.env,
			MCP_PROXY_PORT: String(proxyPort),
			MCP_PROXY_UPSTREAM: `http://127.0.0.1:${upstream.port}/mcp`,
			MCP_PROXY_AUTH_ENV: "SINGLE_TOKEN",
			MCP_PROXY_RETRY_SECS: "0",
			SINGLE_TOKEN: "single-secret",
		},
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	const response = await fetch(`http://127.0.0.1:${proxyPort}/ignored/client/path`, { method: "POST", body: "{}" })
	assert.equal(response.status, 200)
	assert.deepEqual(upstream.requests.map(({ url, authorization }) => ({ url, authorization })), [
		{ url: "/mcp", authorization: "Bearer single-secret" },
	])
})

test("fixed-prefix mode strips one cloud project route and rejects every other route", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const child = spawn(process.execPath, [proxyPath, "test-fixed-prefix"], {
		env: {
			...process.env,
			MCP_PROXY_PORT: String(proxyPort),
			MCP_PROXY_UPSTREAM: `http://127.0.0.1:${upstream.port}`,
			MCP_PROXY_PREFIX: "/workflow-pro",
			MCP_PROXY_AUTH_ENV: "SINGLE_TOKEN",
			MCP_PROXY_RETRY_SECS: "0",
			SINGLE_TOKEN: "workflow-secret",
		},
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	let response = await fetch(`http://127.0.0.1:${proxyPort}/workflow-pro/session-init`, {
		method: "POST",
		body: "{}",
	})
	assert.equal(response.status, 200)
	response = await fetch(`http://127.0.0.1:${proxyPort}/ts/mcp`, { method: "POST", body: "{}" })
	assert.equal(response.status, 404)
	assert.deepEqual(upstream.requests.map(({ url, authorization }) => ({ url, authorization })), [
		{ url: "/session-init", authorization: "Bearer workflow-secret" },
	])
})

test("optional-auth mode omits authorization for the rate-limited Context7 route", async (t) => {
	const upstream = await startUpstream()
	t.after(() => new Promise((resolve) => upstream.server.close(resolve)))
	const proxyPort = await freePort()
	const child = spawn(process.execPath, [proxyPath, "test-optional-auth"], {
		env: {
			...process.env,
			MCP_PROXY_PORT: String(proxyPort),
			MCP_PROXY_UPSTREAM: `http://127.0.0.1:${upstream.port}/mcp`,
			MCP_PROXY_AUTH_ENV: "ABSENT_CONTEXT7_TOKEN",
			MCP_PROXY_AUTH_OPTIONAL: "1",
			MCP_PROXY_RETRY_SECS: "0",
		},
		stdio: "ignore",
	})
	t.after(() => stop(child))
	await waitForPort(proxyPort, child)

	const response = await fetch(`http://127.0.0.1:${proxyPort}/`, { method: "POST", body: "{}" })
	assert.equal(response.status, 200)
	assert.deepEqual(upstream.requests.map(({ authorization }) => authorization), [undefined])
})
