import assert from "node:assert/strict"
import { test } from "node:test"

import {
	filterToolsListResponse,
	MAX_ALLOWLIST_RESPONSE_BYTES,
	ToolFilterError,
} from "./lib/tool-filter.mjs"

const json = (value) => Buffer.from(JSON.stringify(value), "utf8")
function paddedJson(value, bytes) {
	const encoded = json(value)
	assert.ok(encoded.length <= bytes)
	return Buffer.concat([encoded, Buffer.alloc(bytes - encoded.length, " ")])
}
const headers = {
	"content-type": "Application/JSON; Charset=UTF-8",
	"content-length": "999",
	"transfer-encoding": "chunked",
	"content-encoding": "identity",
	etag: "old",
	"last-modified": "yesterday",
	"mcp-session-id": "session-1",
}

test("plain JSON tools/list is filtered in upstream order and retains safe fields", () => {
	const allowedSchema = { name: "allowed", description: "kept", inputSchema: { type: "object" } }
	const result = filterToolsListResponse(json({
		jsonrpc: "2.0",
		id: 7,
		result: {
			tools: [
				{ name: "denied", description: "secret-description-canary" },
				allowedSchema,
				{ name: "other", description: "also kept" },
			],
			nextCursor: "cursor",
		},
		meta: { retained: true },
	}), headers, ["other", "allowed"])
	const message = JSON.parse(result.body.toString("utf8"))
	assert.deepEqual(message.result.tools, [allowedSchema, {
		name: "other",
		description: "also kept",
	}])
	assert.equal(message.result.nextCursor, "cursor")
	assert.deepEqual(message.meta, { retained: true })
	assert.equal(result.headers["mcp-session-id"], "session-1")
	assert.equal(result.headers["content-length"], String(result.body.length))
	assert.equal(result.headers["content-type"], "application/json; charset=utf-8")
	for (const name of [
		"transfer-encoding",
		"content-encoding",
		"etag",
		"last-modified",
	]) {
		assert.equal(result.headers[name], undefined)
	}
	assert.ok(!result.body.includes("secret-description-canary"))
})

test("an empty allowlist intersection is a valid response", () => {
	const result = filterToolsListResponse(json({
		jsonrpc: "2.0",
		result: { tools: [{ name: "not-allowed" }] },
	}), { "content-type": "application/json" }, ["allowed"])
	assert.deepEqual(JSON.parse(result.body).result.tools, [])
})

test("duplicate allowed upstream entries remain visible in upstream order", () => {
	const first = { name: "allowed", description: "first" }
	const second = { name: "allowed", description: "second" }
	const result = filterToolsListResponse(json({
		result: { tools: [first, { name: "denied" }, second] },
	}), { "content-type": "application/json" }, ["allowed"])
	assert.deepEqual(JSON.parse(result.body).result.tools, [first, second])
})

test("unsupported content and JSON envelopes fail closed", () => {
	const valid = json({ result: { tools: [{ name: "allowed" }] } })
	const cases = [
		[valid, { "content-type": "text/event-stream" }, "unsupported_content_type"],
		[valid, {}, "unsupported_content_type"],
		[valid, { "content-type": "application/json; charset=iso-8859-1" },
			"unsupported_content_type"],
		[valid, { "content-type": "application/json", "content-encoding": "gzip" },
			"unsupported_content_encoding"],
		[Buffer.from("{"), { "content-type": "application/json" }, "malformed_json"],
		[json([]), { "content-type": "application/json" }, "invalid_jsonrpc_shape"],
		[json(1), { "content-type": "application/json" }, "invalid_jsonrpc_shape"],
		[json({ jsonrpc: "2.0", error: { code: -32601 } }),
			{ "content-type": "application/json" }, "missing_tools"],
		[json({ result: {} }), { "content-type": "application/json" }, "missing_tools"],
		[json({ result: { tools: null } }), { "content-type": "application/json" },
			"missing_tools"],
		[json({ result: { tools: [null] } }), { "content-type": "application/json" },
			"invalid_tool_entry"],
		[json({ result: { tools: [{ name: 1 }] } }), { "content-type": "application/json" },
			"invalid_tool_entry"],
	]
	for (const [body, responseHeaders, reason] of cases) {
		assert.throws(
			() => filterToolsListResponse(body, responseHeaders, ["allowed"]),
			(error) => error instanceof ToolFilterError &&
				error.reason === reason &&
				!error.message.includes(body.toString("utf8")),
		)
	}
})

test("response body and declared content length are bounded", () => {
	assert.throws(
		() => filterToolsListResponse(
			Buffer.alloc(MAX_ALLOWLIST_RESPONSE_BYTES + 1),
			{ "content-type": "application/json" },
			["allowed"],
		),
		(error) => error instanceof ToolFilterError && error.reason === "response_too_large",
	)
	assert.throws(
		() => filterToolsListResponse(
			json({ result: { tools: [] } }),
			{
				"content-type": "application/json",
				"content-length": String(MAX_ALLOWLIST_RESPONSE_BYTES + 1),
			},
			["allowed"],
		),
		(error) => error instanceof ToolFilterError && error.reason === "response_too_large",
	)
})

test("a valid response exactly at the size limit is filtered", () => {
	const result = filterToolsListResponse(
		paddedJson({
			jsonrpc: "2.0",
			result: { tools: [{ name: "allowed" }, { name: "denied" }] },
		}, MAX_ALLOWLIST_RESPONSE_BYTES),
		{
			"content-type": "application/json",
			"content-length": String(MAX_ALLOWLIST_RESPONSE_BYTES),
		},
		["allowed"],
	)
	assert.deepEqual(JSON.parse(result.body).result.tools, [{ name: "allowed" }])
})

test("malformed UTF-8 is rejected", () => {
	assert.throws(
		() => filterToolsListResponse(
			Buffer.from([0xc3, 0x28]),
			{ "content-type": "application/json" },
			["allowed"],
		),
		(error) => error instanceof ToolFilterError && error.reason === "malformed_json",
	)
})
