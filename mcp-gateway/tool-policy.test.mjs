import assert from "node:assert/strict"
import { test } from "node:test"

import {
	inspectAllowlistedRequest,
	MAX_ALLOWLIST_REQUEST_BYTES,
	sanitizeToolLabel,
	toolPolicyAudit,
} from "./lib/tool-policy.mjs"

const headers = { "content-type": "application/json" }
const body = (value) => Buffer.from(JSON.stringify(value), "utf8")
function paddedBody(value, bytes) {
	const encoded = body(value)
	assert.ok(encoded.length <= bytes)
	return Buffer.concat([encoded, Buffer.alloc(bytes - encoded.length, " ")])
}
const inspect = (value, overrides = {}) => inspectAllowlistedRequest({
	method: "POST",
	headers,
	body: body(value),
	allowTools: ["search", "create_artifact"],
	...overrides,
})

test("allowed tools/call and tools/list requests are classified", () => {
	assert.equal(inspect({
		jsonrpc: "2.0",
		method: "tools/call",
		params: { name: "search", arguments: {} },
	}).allowed, true)
	const list = inspect({ jsonrpc: "2.0", method: "tools/list", params: {} })
	assert.equal(list.allowed, true)
	assert.equal(list.isToolsList, true)
	assert.equal(inspect({ jsonrpc: "2.0", method: "initialize", params: {} }).allowed, true)
})

test("disallowed and malformed tool names fail closed", () => {
	const cases = [
		[{ method: "tools/call", params: { name: "delete_ticket" } }, "tool_not_allowed"],
		[{ method: "tools/call", params: {} }, "invalid_tool_name"],
		[{ method: "tools/call", params: null }, "invalid_tool_name"],
		[{ method: "tools/call", params: [] }, "invalid_tool_name"],
		[{ method: "tools/call", params: { name: 7 } }, "invalid_tool_name"],
	]
	for (const [message, reason] of cases) {
		const result = inspect(message)
		assert.equal(result.allowed, false)
		assert.equal(result.status, 403)
		assert.equal(result.reason, reason)
	}
})

test("batch, primitive, malformed, compressed, and oversized bodies fail closed", () => {
	for (const batch of [
		[],
		[{ method: "tools/call", params: { name: "search" } }],
		[
			{ method: "notifications/initialized" },
			{ method: "tools/call", params: { name: "delete_ticket" } },
		],
	]) {
		const decision = inspectAllowlistedRequest({
			method: "POST", headers, body: body(batch), allowTools: ["search"],
		})
		assert.equal(decision.allowed, false)
		assert.equal(decision.status, 403)
		assert.equal(decision.reason, "batch_not_allowed")
	}
	assert.equal(inspectAllowlistedRequest({
		method: "POST", headers, body: body("primitive"), allowTools: ["search"],
	}).reason, "invalid_jsonrpc_shape")
	assert.equal(inspectAllowlistedRequest({
		method: "POST", headers, body: body({}), allowTools: ["search"],
	}).reason, "invalid_jsonrpc_shape")
	assert.equal(inspectAllowlistedRequest({
		method: "POST", headers, body: Buffer.from("{"), allowTools: ["search"],
	}).reason, "malformed_json")
	assert.equal(inspectAllowlistedRequest({
		method: "POST", headers, body: Buffer.from([0xc3, 0x28]), allowTools: ["search"],
	}).reason, "malformed_json")
	assert.equal(inspectAllowlistedRequest({
		method: "POST",
		headers: { ...headers, "content-encoding": "gzip" },
		body: body({ method: "tools/call", params: { name: "search" } }),
		allowTools: ["search"],
	}).reason, "unsupported_content_encoding")
	assert.equal(inspectAllowlistedRequest({
		method: "POST",
		headers: { "content-type": "text/plain" },
		body: body({ method: "tools/call", params: { name: "search" } }),
		allowTools: ["search"],
	}).reason, "unsupported_content_type")
	assert.equal(inspectAllowlistedRequest({
		method: "POST",
		headers,
		body: Buffer.alloc(MAX_ALLOWLIST_REQUEST_BYTES + 1),
		allowTools: ["search"],
	}).reason, "request_too_large")
})

test("an allowlisted request exactly at the size limit is accepted", () => {
	const decision = inspectAllowlistedRequest({
		method: "POST",
		headers: { "content-type": "Application/JSON; Charset=UTF-8" },
		body: paddedBody(
			{ jsonrpc: "2.0", method: "tools/call", params: { name: "search" } },
			MAX_ALLOWLIST_REQUEST_BYTES,
		),
		allowTools: ["search"],
	})
	assert.equal(decision.allowed, true)
})

test("unrestricted routes preserve arbitrary request bodies", () => {
	const arbitrary = Buffer.from([0, 1, 2, 255])
	const decision = inspectAllowlistedRequest({
		method: "POST",
		headers: { "content-encoding": "gzip" },
		body: arbitrary,
		allowTools: undefined,
	})
	assert.equal(decision.allowed, true)
	assert.equal(decision.isToolsList, false)
})

test("denial audit has a bounded secret-free label", () => {
	const canary = "token-like-canary\nsecond-line"
	const audit = toolPolicyAudit(
		{ prefix: "hermes/test" },
		"tool_not_allowed",
		canary,
	)
	assert.deepEqual(audit, {
		event: "mcp_gateway_tool_policy_denied",
		route: "hermes/test",
		tool: "<redacted>",
		reason: "tool_not_allowed",
		outcome: "denied",
	})
	assert.ok(!JSON.stringify(audit).includes(canary))
	assert.equal(sanitizeToolLabel(undefined), "<invalid>")
})
