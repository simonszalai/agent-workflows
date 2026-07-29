// WAF base64 encoder for autodev-memory write tool-calls.
//
// Render's edge WAF 403s autodev-memory writes whose JSON-RPC body contains SQL / shell
// literals (knowledge about DBs/migrations/deploys naturally does). This base64-encodes the
// free-text fields of write `tools/call` requests — prefixed with a sentinel the autodev-memory
// server decodes in matching middleware — so the bytes crossing the WAF carry no injection
// signatures. Best-effort and transparent: any parse/shape mismatch returns the original body
// unchanged, so the proxy never breaks and non-write / read calls are untouched.
//
// Paired with: autodev-memory src/mcp_tools.py `WafBase64DecodeMiddleware` (same sentinel).

export const WAF_B64_SENTINEL = "@@B64@@"

// Only the long free-text fields that trip the WAF — never ids/enums/types (which the server
// may validate before the decode middleware runs).
const ENCODE_FIELDS = ["content", "summary", "description", "project_description"]
const WRITE_TOOL_RE = /^(create|update|absorb)_/

/**
 * Given a buffered JSON-RPC request body (Buffer), return a Buffer with the free-text fields of
 * a write `tools/call` base64-encoded. Returns the original buffer unchanged on anything
 * unexpected (not JSON, not a write tools/call, no encodable fields, already encoded).
 * @param {Buffer} buf
 * @returns {Buffer}
 */
export function encodeAutodevWriteBody(buf) {
	try {
		const text = buf.toString("utf8")
		const msg = JSON.parse(text)
		if (!msg || msg.method !== "tools/call" || !msg.params) return buf
		const { name, arguments: args } = msg.params
		if (typeof name !== "string" || !WRITE_TOOL_RE.test(name)) return buf
		if (!args || typeof args !== "object" || Array.isArray(args)) return buf

		let changed = false
		for (const field of ENCODE_FIELDS) {
			const v = args[field]
			if (typeof v === "string" && v.length > 0 && !v.startsWith(WAF_B64_SENTINEL)) {
				args[field] = WAF_B64_SENTINEL + Buffer.from(v, "utf8").toString("base64")
				changed = true
			}
		}
		return changed ? Buffer.from(JSON.stringify(msg), "utf8") : buf
	} catch {
		return buf
	}
}
