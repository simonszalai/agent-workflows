// Tests for the WAF base64 encoder (paired with autodev-memory's decode middleware).
// Run: node --test mcp-gateway/waf-encode.test.mjs

import { test } from "node:test"
import assert from "node:assert/strict"
import { encodeAutodevWriteBody, WAF_B64_SENTINEL } from "./waf-encode.mjs"

const buf = (o) => Buffer.from(JSON.stringify(o), "utf8")
const parse = (b) => JSON.parse(b.toString("utf8"))
const decode = (v) => Buffer.from(v.slice(WAF_B64_SENTINEL.length), "base64").toString("utf8")

test("encodes free-text fields of a write tools/call, leaves other fields alone", () => {
	const body = buf({
		jsonrpc: "2.0", id: 1, method: "tools/call",
		params: {
			name: "create_entry",
			arguments: { title: "t", entry_type: "gotcha", content: "SELECT * FROM x;", summary: "a & b" },
		},
	})
	const a = parse(encodeAutodevWriteBody(body)).params.arguments
	assert.ok(a.content.startsWith(WAF_B64_SENTINEL))
	assert.equal(decode(a.content), "SELECT * FROM x;")
	assert.ok(a.summary.startsWith(WAF_B64_SENTINEL))
	assert.equal(a.title, "t") // non-target field untouched
	assert.equal(a.entry_type, "gotcha") // enum untouched (server may validate before decode)
})

test("encodes description and project_description too", () => {
	const body = buf({ method: "tools/call", params: { name: "create_ticket",
		arguments: { description: "UPDATE t SET x=1;" } } })
	const a = parse(encodeAutodevWriteBody(body)).params.arguments
	assert.equal(decode(a.description), "UPDATE t SET x=1;")
})

test("leaves non-write (read) tool-calls untouched", () => {
	const body = buf({ method: "tools/call", params: { name: "search",
		arguments: { queries: [{ text: "SELECT 1" }] } } })
	assert.equal(encodeAutodevWriteBody(body).toString("utf8"), body.toString("utf8"))
})

test("leaves non-tools/call messages untouched", () => {
	const body = buf({ method: "initialize", params: {} })
	assert.equal(encodeAutodevWriteBody(body).toString("utf8"), body.toString("utf8"))
})

test("idempotent: does not double-encode an already-encoded field", () => {
	const body = buf({ method: "tools/call", params: { name: "create_entry",
		arguments: { content: "x" } } })
	const once = encodeAutodevWriteBody(body)
	const twice = encodeAutodevWriteBody(once)
	assert.equal(twice.toString("utf8"), once.toString("utf8"))
})

test("non-JSON / malformed body passes through unchanged", () => {
	assert.equal(encodeAutodevWriteBody(Buffer.from("not json", "utf8")).toString("utf8"), "not json")
})

test("round-trips with standard base64 (what the Python server decodes)", () => {
	const original = "UPDATE t SET x=1; -- pg_advisory_lock(1); shell: a && . file"
	const body = buf({ method: "tools/call", params: { name: "update_entry",
		arguments: { content: original } } })
	assert.equal(decode(parse(encodeAutodevWriteBody(body)).params.arguments.content), original)
})
