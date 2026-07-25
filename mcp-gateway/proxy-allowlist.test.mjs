import assert from "node:assert/strict"
import http from "node:http"
import { once } from "node:events"
import { test } from "node:test"

import { createRequestHandler } from "./lib/proxy.mjs"
import { MAX_ALLOWLIST_REQUEST_BYTES } from "./lib/tool-policy.mjs"
import { MAX_ALLOWLIST_RESPONSE_BYTES } from "./lib/tool-filter.mjs"
import { WAF_B64_SENTINEL } from "./waf-encode.mjs"

async function listen(server) {
	server.listen(0, "127.0.0.1")
	await once(server, "listening")
	return server.address().port
}

async function close(server) {
	server.closeAllConnections?.()
	server.close()
	await once(server, "close")
}

function request(port, {
	path,
	method = "POST",
	token,
	body,
	headers = {},
	chunked = false,
}) {
	return new Promise((resolve, reject) => {
		const payload = body === undefined
			? null
			: Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body), "utf8")
		const requestHeaders = { ...headers }
		if (token !== undefined) requestHeaders["x-mcp-gateway-token"] = token
		if (payload) {
			if (!requestHeaders["content-type"]) requestHeaders["content-type"] = "application/json"
			if (!chunked) requestHeaders["content-length"] = String(payload.length)
		}
		const req = http.request({
			host: "127.0.0.1",
			port,
			path,
			method,
			headers: requestHeaders,
		}, (res) => {
			const chunks = []
			res.on("data", (chunk) => chunks.push(chunk))
			res.on("end", () => resolve({
				status: res.statusCode,
				headers: res.headers,
				body: Buffer.concat(chunks),
			}))
		})
		req.on("error", reject)
		if (payload && chunked) {
			const midpoint = Math.floor(payload.length / 2)
			req.write(payload.subarray(0, midpoint))
			req.end(payload.subarray(midpoint))
		} else if (payload) {
			req.end(payload)
		} else {
			req.end()
		}
	})
}

test("route auth and allowlist boundaries integrate", async () => {
	const savedEnv = {
		MCP_GATEWAY_TOKEN: process.env.MCP_GATEWAY_TOKEN,
		HERMES_GATEWAY_TOKEN: process.env.HERMES_GATEWAY_TOKEN,
		TEST_UPSTREAM_TOKEN: process.env.TEST_UPSTREAM_TOKEN,
		HERMES_UPSTREAM_TOKEN: process.env.HERMES_UPSTREAM_TOKEN,
	}
	process.env.MCP_GATEWAY_TOKEN = "default-client-canary"
	process.env.HERMES_GATEWAY_TOKEN = "hermes-client-canary"
	process.env.TEST_UPSTREAM_TOKEN = "shared-upstream-canary"
	process.env.HERMES_UPSTREAM_TOKEN = "hermes-upstream-canary"

	const observed = {
		requests: 0,
		bodies: [],
		headers: [],
	}
	const fake = http.createServer((req, res) => {
		const chunks = []
		req.on("data", (chunk) => chunks.push(chunk))
		req.on("end", () => {
			const body = Buffer.concat(chunks)
			observed.requests += 1
			observed.bodies.push(body)
			observed.headers.push(req.headers)
			const fixture = req.headers["x-test-fixture"]
			if (fixture === "tools-list") {
				const responseBody = Buffer.from(JSON.stringify({
					jsonrpc: "2.0",
					id: 1,
					result: {
						tools: [
							{ name: "delete_ticket", description: "hidden-description-canary" },
							{ name: "search", description: "allowed" },
						],
						nextCursor: "next",
					},
				}), "utf8")
				res.writeHead(200, {
					"content-type": "application/json; charset=utf-8",
					"content-length": String(responseBody.length),
					"content-encoding": "identity",
					etag: "stale",
					"mcp-session-id": "fake-session",
				})
				res.end(responseBody)
				return
			}
			if (fixture === "sse") {
				res.writeHead(200, { "content-type": "text/event-stream" })
				res.write("event: message\n")
				res.end("data: exact-sse-bytes\n\n")
				return
			}
			if (fixture === "malformed") {
				res.writeHead(200, { "content-type": "application/json" })
				res.end("{")
				return
			}
			if (fixture === "compressed") {
				res.writeHead(200, {
					"content-type": "application/json",
					"content-encoding": "gzip",
				})
				res.end(JSON.stringify({ result: { tools: [{ name: "search" }] } }))
				return
			}
			if (fixture === "oversized") {
				res.writeHead(200, { "content-type": "application/json" })
				res.end(Buffer.alloc(MAX_ALLOWLIST_RESPONSE_BYTES + 1, "x"))
				return
			}
			if (fixture === "missing-tools") {
				res.writeHead(200, { "content-type": "application/json" })
				res.end(JSON.stringify({
					jsonrpc: "2.0",
					result: {},
					description: "upstream-filter-secret-canary",
				}))
				return
			}
			if (fixture === "array") {
				res.writeHead(200, { "content-type": "application/json" })
				res.end("[]")
				return
			}
			if (fixture === "primitive") {
				res.writeHead(200, { "content-type": "application/json" })
				res.end("1")
				return
			}
			if (fixture === "aborted") {
				res.writeHead(200, { "content-type": "application/json" })
				res.flushHeaders()
				res.write('{"result":{"tools":[')
				setImmediate(() => res.destroy())
				return
			}
			if (fixture === "opaque-unrestricted") {
				res.writeHead(207, {
					"content-type": "application/octet-stream",
					"x-upstream-canary": "preserved",
				})
				res.end(Buffer.from([255, 0, 128, 1]))
				return
			}
			res.writeHead(200, {
				"content-type": req.url.startsWith("/sse-unrestricted")
					? "text/event-stream"
					: "application/octet-stream",
			})
			res.end(req.url.startsWith("/sse-unrestricted")
				? "event: message\ndata: unchanged\n\n"
				: body)
		})
	})

	let fakePort
	let gateway
	try {
		fakePort = await listen(fake)
		const target = `http://127.0.0.1:${fakePort}`
		const routes = [
			{
				prefix: "shared/test",
				target: `${target}/echo`,
				authEnv: "TEST_UPSTREAM_TOKEN",
				clientTokenEnv: "MCP_GATEWAY_TOKEN",
			},
			{
				prefix: "shared/sse",
				target: `${target}/sse-unrestricted`,
				authEnv: "TEST_UPSTREAM_TOKEN",
				clientTokenEnv: "MCP_GATEWAY_TOKEN",
			},
			{
				prefix: "hermes/test",
				target: `${target}/mcp`,
				authEnv: "HERMES_UPSTREAM_TOKEN",
				clientTokenEnv: "HERMES_GATEWAY_TOKEN",
				allowTools: ["search", "create_artifact"],
			},
			{
				prefix: "hermes/autodev",
				target: `${target}/autodev-memory`,
				authEnv: "HERMES_UPSTREAM_TOKEN",
				clientTokenEnv: "HERMES_GATEWAY_TOKEN",
				allowTools: ["create_artifact"],
			},
			{
				prefix: "hermes/render",
				target: `${target}/render`,
				authEnv: "HERMES_UPSTREAM_TOKEN",
				clientTokenEnv: "HERMES_GATEWAY_TOKEN",
				renderWorkspace: "fake-owner",
				allowTools: ["get_service"],
			},
		]
		const audit = []
		gateway = http.createServer(createRequestHandler(
			() => routes,
			{ logger: (...args) => audit.push(args.join(" ")) },
		))
		const gatewayPort = await listen(gateway)

		const health = await request(gatewayPort, { path: "/healthz", method: "GET" })
		assert.equal(health.status, 200)

		const arbitrary = Buffer.from([0, 1, 2, 254, 255])
		const shared = await request(gatewayPort, {
			path: "/shared/test",
			token: "default-client-canary",
			body: arbitrary,
			headers: { "content-type": "application/octet-stream" },
		})
		assert.equal(shared.status, 200)
		assert.deepEqual(shared.body, arbitrary)
		assert.equal(observed.headers.at(-1)["x-mcp-gateway-token"], undefined)
		assert.equal(observed.headers.at(-1).authorization, "Bearer shared-upstream-canary")

		const beforeAuthDenials = observed.requests
		for (const authAttempt of [
			{},
			{ token: "" },
			{
				headers: {
					"x-mcp-gateway-token": [
						"default-client-canary",
						"hermes-client-canary",
					],
				},
			},
		]) {
			assert.equal((await request(gatewayPort, {
				path: "/shared/test",
				body: arbitrary,
				...authAttempt,
			})).status, 401)
		}
		assert.equal(observed.requests, beforeAuthDenials)

		assert.equal((await request(gatewayPort, {
			path: "/shared/test",
			token: "hermes-client-canary",
			body: arbitrary,
		})).status, 401)
		assert.equal((await request(gatewayPort, {
			path: "/hermes/test",
			token: "default-client-canary",
			body: { method: "tools/call", params: { name: "search" } },
		})).status, 401)

		const beforeDisabled = observed.requests
		delete process.env.HERMES_GATEWAY_TOKEN
		const missingClient = await request(gatewayPort, {
			path: "/hermes/test",
			token: "hermes-client-canary",
			body: { method: "tools/call", params: { name: "search" } },
		})
		assert.equal(missingClient.status, 503)
		assert.ok(!missingClient.body.includes("HERMES_GATEWAY_TOKEN"))
		assert.ok(!missingClient.body.includes("hermes-client-canary"))
		assert.equal(observed.requests, beforeDisabled)
		process.env.HERMES_GATEWAY_TOKEN = "hermes-client-canary"

		delete process.env.HERMES_UPSTREAM_TOKEN
		const missingUpstream = await request(gatewayPort, {
			path: "/hermes/test",
			token: "hermes-client-canary",
			body: { method: "tools/call", params: { name: "search" } },
		})
		assert.equal(missingUpstream.status, 503)
		assert.ok(!missingUpstream.body.includes("HERMES_UPSTREAM_TOKEN"))
		assert.ok(!missingUpstream.body.includes("hermes-upstream-canary"))
		assert.equal(observed.requests, beforeDisabled)
		process.env.HERMES_UPSTREAM_TOKEN = "hermes-upstream-canary"

		process.env.HERMES_GATEWAY_TOKEN = "default-client-canary"
		const collision = await request(gatewayPort, {
			path: "/hermes/test",
			token: "default-client-canary",
			body: { method: "tools/call", params: { name: "search" } },
		})
		assert.equal(collision.status, 503)
		assert.equal(observed.requests, beforeDisabled)
		process.env.HERMES_GATEWAY_TOKEN = "hermes-client-canary"

		const beforeAllowed = observed.requests
		const allowed = await request(gatewayPort, {
			path: "/hermes/test",
			token: "hermes-client-canary",
			body: { method: "tools/call", params: { name: "search", arguments: {} } },
		})
		assert.equal(allowed.status, 200)
		assert.equal(observed.requests, beforeAllowed + 1)

		const deniedCases = [
			{
				name: "disallowed tool",
				body: { method: "tools/call", params: { name: "delete_ticket-secret-canary" } },
			},
			{ name: "missing name", body: { method: "tools/call", params: {} } },
			{ name: "null params", body: { method: "tools/call", params: null } },
			{ name: "array params", body: { method: "tools/call", params: [] } },
			{
				name: "non-string name",
				body: { method: "tools/call", params: { name: 7 } },
			},
			{ name: "malformed JSON", body: Buffer.from("{") },
			{ name: "empty body", body: undefined },
			{ name: "primitive JSON", body: "primitive-secret-canary" },
			{ name: "empty object", body: {} },
			{
				name: "allowed batch",
				body: [{ method: "tools/call", params: { name: "search" } }],
			},
			{
				name: "mixed batch",
				body: [
					{ method: "notifications/initialized" },
					{ method: "tools/call", params: { name: "search" } },
				],
			},
			{
				name: "compressed body",
				body: { method: "tools/call", params: { name: "search" } },
				headers: { "content-encoding": "gzip" },
			},
			{
				name: "unsupported media type",
				body: { method: "tools/call", params: { name: "search" } },
				headers: { "content-type": "text/plain" },
			},
			{
				name: "oversized body",
				body: Buffer.alloc(MAX_ALLOWLIST_REQUEST_BYTES + 1, "x"),
			},
			{
				name: "chunked oversized body",
				body: Buffer.alloc(MAX_ALLOWLIST_REQUEST_BYTES + 1, "x"),
				chunked: true,
			},
			{
				name: "non-POST oversized body",
				method: "PUT",
				body: Buffer.alloc(MAX_ALLOWLIST_REQUEST_BYTES + 1, "x"),
			},
		]
		for (const denied of deniedCases) {
			const before = observed.requests
			const auditBefore = audit.length
			const result = await request(gatewayPort, {
				path: "/hermes/test",
				token: "hermes-client-canary",
				method: denied.method,
				body: denied.body,
				headers: denied.headers,
				chunked: denied.chunked,
			})
			assert.equal(result.status, 403, denied.name)
			assert.equal(observed.requests, before, denied.name)
			assert.equal(audit.length, auditBefore + 1, denied.name)
			assert.match(audit.at(-1), /mcp_gateway_tool_policy_denied/, denied.name)
			assert.ok(!result.body.includes("secret-canary"), denied.name)
			assert.ok(!audit.at(-1).includes("secret-canary"), denied.name)
		}

		const beforeRenderDeny = observed.requests
		const auditBeforeRenderDeny = audit.length
		assert.equal((await request(gatewayPort, {
			path: "/hermes/render",
			token: "hermes-client-canary",
			body: { method: "tools/call", params: { name: "trigger_deploy" } },
		})).status, 403)
		assert.equal(observed.requests, beforeRenderDeny)
		assert.equal(audit.length, auditBeforeRenderDeny + 1)

		const writeCanary = "SELECT secret write canary"
		const write = await request(gatewayPort, {
			path: "/hermes/autodev",
			token: "hermes-client-canary",
			body: {
				method: "tools/call",
				params: {
					name: "create_artifact",
					arguments: { description: writeCanary },
				},
			},
		})
		assert.equal(write.status, 200)
		const encoded = JSON.parse(observed.bodies.at(-1).toString("utf8"))
		assert.ok(encoded.params.arguments.description.startsWith(WAF_B64_SENTINEL))
		assert.ok(!observed.bodies.at(-1).includes(writeCanary))

		const beforeList = observed.requests
		const list = await request(gatewayPort, {
			path: "/hermes/test",
			token: "hermes-client-canary",
			body: { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
			headers: { "x-test-fixture": "tools-list" },
		})
		assert.equal(list.status, 200)
		assert.equal(observed.requests, beforeList + 1)
		assert.deepEqual(JSON.parse(list.body).result.tools, [
			{ name: "search", description: "allowed" },
		])
		assert.equal(list.headers["content-length"], String(list.body.length))
		assert.equal(list.headers["content-encoding"], undefined)
		assert.equal(list.headers.etag, undefined)
		assert.equal(list.headers["mcp-session-id"], "fake-session")
		assert.ok(!list.body.includes("hidden-description-canary"))

		for (const fixture of [
			"sse",
			"malformed",
			"compressed",
			"oversized",
			"missing-tools",
			"array",
			"primitive",
			"aborted",
		]) {
			const before = observed.requests
			const auditBefore = audit.length
			const result = await request(gatewayPort, {
				path: "/hermes/test",
				token: "hermes-client-canary",
				body: { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
				headers: { "x-test-fixture": fixture },
			})
			assert.equal(result.status, 403, fixture)
			assert.equal(observed.requests, before + 1, fixture)
			assert.equal(audit.length, auditBefore + 1, fixture)
			assert.match(audit.at(-1), /mcp_gateway_tool_list_filter_denied/, fixture)
			assert.ok(!result.body.includes("hidden-description-canary"), fixture)
			assert.ok(!result.body.includes("upstream-filter-secret-canary"), fixture)
			assert.ok(!audit.at(-1).includes("upstream-filter-secret-canary"), fixture)
		}

		const allowlistedSse = await request(gatewayPort, {
			path: "/hermes/test",
			method: "GET",
			token: "hermes-client-canary",
			headers: { "x-test-fixture": "sse" },
		})
		assert.equal(allowlistedSse.status, 200)
		assert.equal(allowlistedSse.headers["content-type"], "text/event-stream")
		assert.equal(allowlistedSse.body.toString("utf8"),
			"event: message\ndata: exact-sse-bytes\n\n")

		const sse = await request(gatewayPort, {
			path: "/shared/sse",
			token: "default-client-canary",
			body: Buffer.from("unrestricted-request"),
			headers: {
				"content-type": "application/octet-stream",
				"x-test-fixture": "sse",
			},
		})
		assert.equal(sse.status, 200)
		assert.equal(sse.headers["content-type"], "text/event-stream")
		assert.equal(sse.body.toString("utf8"), "event: message\ndata: exact-sse-bytes\n\n")

		const opaqueRequest = Buffer.from([4, 3, 2, 1, 0])
		const opaque = await request(gatewayPort, {
			path: "/shared/test",
			token: "default-client-canary",
			body: opaqueRequest,
			headers: {
				"content-type": "application/octet-stream",
				"x-test-fixture": "opaque-unrestricted",
			},
		})
		assert.equal(opaque.status, 207)
		assert.equal(opaque.headers["x-upstream-canary"], "preserved")
		assert.deepEqual(opaque.body, Buffer.from([255, 0, 128, 1]))
		assert.deepEqual(observed.bodies.at(-1), opaqueRequest)
	} finally {
		if (gateway) await close(gateway)
		await close(fake)
		for (const [name, value] of Object.entries(savedEnv)) {
			if (value === undefined) delete process.env[name]
			else process.env[name] = value
		}
	}
})

test("protected spawn activation is lazy and occurs only after successful route authentication", async () => {
	const savedToken = process.env.HERMES_GATEWAY_TOKEN
	delete process.env.HERMES_GATEWAY_TOKEN
	let fake
	let gateway
	try {
		let upstreamRequests = 0
		fake = http.createServer((req, res) => {
			req.resume()
			req.on("end", () => {
				upstreamRequests += 1
				res.writeHead(200, { "content-type": "application/json" })
				res.end("{}")
			})
		})
		const fakePort = await listen(fake)
		const routes = [{
			prefix: "hermes/spawn",
			target: `http://127.0.0.1:${fakePort}/mcp`,
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			allowTools: ["search"],
			spawn: {
				kind: "generic",
				port: fakePort,
			},
		}]
		let activations = 0
		gateway = http.createServer(createRequestHandler(() => routes, {
			ensureRouteRunning: () => {
				activations += 1
				return {}
			},
		}))
		const gatewayPort = await listen(gateway)
		const body = { method: "tools/call", params: { name: "search" } }

		assert.equal((await request(gatewayPort, {
			path: "/hermes/spawn",
			token: "hermes-lazy-canary",
			body,
		})).status, 503)
		assert.equal(activations, 0)

		process.env.HERMES_GATEWAY_TOKEN = "hermes-lazy-canary"
		assert.equal((await request(gatewayPort, {
			path: "/hermes/spawn",
			token: "wrong-token",
			body,
		})).status, 401)
		assert.equal(activations, 0)
		assert.equal(upstreamRequests, 0)

		assert.equal((await request(gatewayPort, {
			path: "/hermes/spawn",
			token: "hermes-lazy-canary",
			body,
		})).status, 200)
		assert.equal(activations, 1)
		assert.equal(upstreamRequests, 1)
	} finally {
		if (gateway) await close(gateway)
		if (fake) await close(fake)
		if (savedToken === undefined) delete process.env.HERMES_GATEWAY_TOKEN
		else process.env.HERMES_GATEWAY_TOKEN = savedToken
	}
})

test("allowlisted buffering rejects excess concurrency before upstream dispatch", async () => {
	const savedToken = process.env.HERMES_GATEWAY_TOKEN
	const savedDefaultToken = process.env.MCP_GATEWAY_TOKEN
	process.env.HERMES_GATEWAY_TOKEN = "hermes-buffer-canary"
	process.env.MCP_GATEWAY_TOKEN = "trusted-buffer-canary"
	let fake
	let gateway
	let releaseFirst
	let firstDispatched
	try {
		const firstSeen = new Promise((resolve) => { firstDispatched = resolve })
		const release = new Promise((resolve) => { releaseFirst = resolve })
		let upstreamRequests = 0
		fake = http.createServer((req, res) => {
			req.on("end", async () => {
				upstreamRequests += 1
				if (req.url === "/shared") {
					res.writeHead(200, { "content-type": "application/octet-stream" })
					res.end("trusted")
					return
				}
				if (req.method === "GET") {
					res.writeHead(200, { "content-type": "text/event-stream" })
					res.end("event: message\ndata: bodyless\n\n")
					return
				}
				firstDispatched()
				await release
				res.writeHead(200, { "content-type": "application/json" })
				res.end("{}")
			})
			req.resume()
		})
		const fakePort = await listen(fake)
		const routes = [{
			prefix: "hermes/test",
			target: `http://127.0.0.1:${fakePort}/mcp`,
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			allowTools: ["search"],
		}, {
			prefix: "shared/test",
			target: `http://127.0.0.1:${fakePort}/shared`,
			clientTokenEnv: "MCP_GATEWAY_TOKEN",
		}]
		gateway = http.createServer(createRequestHandler(() => routes, {
			bufferLimits: {
				maxActive: 1,
				maxBytes: 1024,
				requestBodyMs: 1000,
				responseBodyMs: 1000,
			},
		}))
		const gatewayPort = await listen(gateway)
		const first = request(gatewayPort, {
			path: "/hermes/test",
			method: "PUT",
			token: "hermes-buffer-canary",
			body: Buffer.from("first non-POST body"),
			headers: { "content-type": "application/octet-stream" },
		})
		await firstSeen

		const denied = await request(gatewayPort, {
			path: "/hermes/test",
			method: "PATCH",
			token: "hermes-buffer-canary",
			body: Buffer.from("second non-POST body"),
			headers: { "content-type": "application/octet-stream" },
		})
		assert.equal(denied.status, 429)
		assert.equal(upstreamRequests, 1)

		const bodylessSse = await request(gatewayPort, {
			path: "/hermes/test",
			method: "GET",
			token: "hermes-buffer-canary",
		})
		assert.equal(bodylessSse.status, 200)
		assert.equal(bodylessSse.headers["content-type"], "text/event-stream")
		assert.equal(bodylessSse.body.toString("utf8"),
			"event: message\ndata: bodyless\n\n")
		assert.equal(upstreamRequests, 2)

		const trusted = await request(gatewayPort, {
			path: "/shared/test",
			token: "trusted-buffer-canary",
			body: Buffer.from("trusted-request"),
			headers: { "content-type": "application/octet-stream" },
		})
		assert.equal(trusted.status, 200)
		assert.equal(trusted.body.toString("utf8"), "trusted")
		assert.equal(upstreamRequests, 3)

		releaseFirst()
		assert.equal((await first).status, 200)
	} finally {
		releaseFirst?.()
		if (gateway) await close(gateway)
		if (fake) await close(fake)
		if (savedToken === undefined) delete process.env.HERMES_GATEWAY_TOKEN
		else process.env.HERMES_GATEWAY_TOKEN = savedToken
		if (savedDefaultToken === undefined) delete process.env.MCP_GATEWAY_TOKEN
		else process.env.MCP_GATEWAY_TOKEN = savedDefaultToken
	}
})

test("allowlisted buffering enforces an aggregate byte budget", async () => {
	const savedToken = process.env.HERMES_GATEWAY_TOKEN
	process.env.HERMES_GATEWAY_TOKEN = "hermes-buffer-canary"
	let fake
	let gateway
	let releaseFirst
	let firstDispatched
	try {
		const firstSeen = new Promise((resolve) => { firstDispatched = resolve })
		const release = new Promise((resolve) => { releaseFirst = resolve })
		let upstreamRequests = 0
		fake = http.createServer((req, res) => {
			req.on("end", async () => {
				upstreamRequests += 1
				firstDispatched()
				await release
				res.writeHead(200, { "content-type": "application/json" })
				res.end("{}")
			})
			req.resume()
		})
		const fakePort = await listen(fake)
		const routes = [{
			prefix: "hermes/test",
			target: `http://127.0.0.1:${fakePort}/mcp`,
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			allowTools: ["search"],
		}]
		const body = {
			method: "tools/call",
			params: { name: "search", arguments: { padding: "x".repeat(80) } },
		}
		const bodyBytes = Buffer.byteLength(JSON.stringify(body))
		gateway = http.createServer(createRequestHandler(() => routes, {
			bufferLimits: {
				maxActive: 2,
				maxBytes: bodyBytes + 8,
				requestBodyMs: 1000,
				responseBodyMs: 1000,
			},
		}))
		const gatewayPort = await listen(gateway)
		const first = request(gatewayPort, {
			path: "/hermes/test",
			method: "PUT",
			token: "hermes-buffer-canary",
			body,
		})
		await firstSeen

		const denied = await request(gatewayPort, {
			path: "/hermes/test",
			method: "PATCH",
			token: "hermes-buffer-canary",
			body,
		})
		assert.equal(denied.status, 429)
		assert.equal(upstreamRequests, 1)

		releaseFirst()
		assert.equal((await first).status, 200)
	} finally {
		releaseFirst?.()
		if (gateway) await close(gateway)
		if (fake) await close(fake)
		if (savedToken === undefined) delete process.env.HERMES_GATEWAY_TOKEN
		else process.env.HERMES_GATEWAY_TOKEN = savedToken
	}
})

test("allowlisted request and filtered response bodies have bounded deadlines", async () => {
	const savedToken = process.env.HERMES_GATEWAY_TOKEN
	process.env.HERMES_GATEWAY_TOKEN = "hermes-deadline-canary"
	let fake
	let gateway
	let stalledClient
	try {
		let upstreamRequests = 0
		fake = http.createServer((req, res) => {
			req.on("end", () => {
				upstreamRequests += 1
				res.writeHead(200, { "content-type": "application/json" })
				res.write('{"jsonrpc":"2.0","id":1,"result":{"tools":[')
			})
			req.resume()
		})
		const fakePort = await listen(fake)
		const routes = [{
			prefix: "hermes/test",
			target: `http://127.0.0.1:${fakePort}/mcp`,
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			allowTools: ["search"],
		}]
		const audit = []
		gateway = http.createServer(createRequestHandler(() => routes, {
			logger: (...args) => audit.push(args.join(" ")),
			bufferLimits: {
				maxActive: 2,
				maxBytes: 1024,
				requestBodyMs: 25,
				responseBodyMs: 25,
			},
		}))
		const gatewayPort = await listen(gateway)

		const requestDeadline = new Promise((resolve, reject) => {
			stalledClient = http.request({
				host: "127.0.0.1",
				port: gatewayPort,
				path: "/hermes/test",
				method: "PUT",
				headers: {
					"x-mcp-gateway-token": "hermes-deadline-canary",
					"content-type": "application/json",
					"transfer-encoding": "chunked",
				},
			}, (res) => {
				res.resume()
				res.on("end", () => resolve(res.statusCode))
			})
			stalledClient.on("error", reject)
			stalledClient.write('{"method":"tools/call"')
		})
		assert.equal(await requestDeadline, 408)
		stalledClient.end()
		assert.equal(upstreamRequests, 0)
		assert.ok(audit.some((entry) => entry.includes("request_body_timeout")))

		const responseDeadline = await request(gatewayPort, {
			path: "/hermes/test",
			token: "hermes-deadline-canary",
			body: { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
		})
		assert.equal(responseDeadline.status, 403)
		assert.equal(upstreamRequests, 1)
		assert.ok(audit.some((entry) => entry.includes("response_body_timeout")))
	} finally {
		stalledClient?.destroy()
		if (gateway) await close(gateway)
		if (fake) await close(fake)
		if (savedToken === undefined) delete process.env.HERMES_GATEWAY_TOKEN
		else process.env.HERMES_GATEWAY_TOKEN = savedToken
	}
})
