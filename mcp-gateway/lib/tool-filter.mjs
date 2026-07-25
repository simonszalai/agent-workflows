export const MAX_ALLOWLIST_RESPONSE_BYTES = 2 * 1024 * 1024

export class ToolFilterError extends Error {
	constructor(reason) {
		super("unsupported tools/list response")
		this.name = "ToolFilterError"
		this.reason = reason
	}
}

function headerValue(headers, name) {
	const value = headers[name]
	if (Array.isArray(value)) return value.join(",")
	return value === undefined ? "" : String(value)
}

function assertJsonContentType(headers) {
	const raw = headerValue(headers, "content-type")
	const parts = raw.split(";").map((part) => part.trim().toLowerCase())
	if (parts[0] !== "application/json") throw new ToolFilterError("unsupported_content_type")
	for (const parameter of parts.slice(1)) {
		if (!parameter) continue
		if (!/^charset\s*=\s*["']?utf-8["']?$/.test(parameter)) {
			throw new ToolFilterError("unsupported_content_type")
		}
	}
}

export function validateToolsListResponseHeaders(headers) {
	assertJsonContentType(headers)
	const encoding = headerValue(headers, "content-encoding").trim().toLowerCase()
	if (encoding && encoding !== "identity") {
		throw new ToolFilterError("unsupported_content_encoding")
	}
	const contentLength = headerValue(headers, "content-length").trim()
	if (contentLength && (!/^\d+$/.test(contentLength) ||
		Number(contentLength) > MAX_ALLOWLIST_RESPONSE_BYTES)) {
		throw new ToolFilterError("response_too_large")
	}
}

export function filterToolsListResponse(body, headers, allowTools) {
	if (!Buffer.isBuffer(body) || body.length > MAX_ALLOWLIST_RESPONSE_BYTES) {
		throw new ToolFilterError("response_too_large")
	}
	validateToolsListResponseHeaders(headers)

	let message
	try {
		message = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body))
	} catch {
		throw new ToolFilterError("malformed_json")
	}
	if (!message || typeof message !== "object" || Array.isArray(message)) {
		throw new ToolFilterError("invalid_jsonrpc_shape")
	}
	if (!message.result || typeof message.result !== "object" ||
		Array.isArray(message.result) || !Array.isArray(message.result.tools)) {
		throw new ToolFilterError("missing_tools")
	}
	for (const tool of message.result.tools) {
		if (!tool || typeof tool !== "object" || Array.isArray(tool) ||
			typeof tool.name !== "string") {
			throw new ToolFilterError("invalid_tool_entry")
		}
	}

	const allowed = new Set(allowTools)
	message.result.tools = message.result.tools.filter((tool) => allowed.has(tool.name))
	const filteredBody = Buffer.from(JSON.stringify(message), "utf8")
	const filteredHeaders = { ...headers }
	for (const name of [
		"content-length",
		"transfer-encoding",
		"trailer",
		"content-encoding",
		"etag",
		"last-modified",
		"content-md5",
		"digest",
		"connection",
		"keep-alive",
		"proxy-authenticate",
		"proxy-authorization",
		"te",
		"upgrade",
	]) {
		delete filteredHeaders[name]
	}
	filteredHeaders["content-type"] = "application/json; charset=utf-8"
	filteredHeaders["content-length"] = String(filteredBody.length)
	return { body: filteredBody, headers: filteredHeaders }
}
