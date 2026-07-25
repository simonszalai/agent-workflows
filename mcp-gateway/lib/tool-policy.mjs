export const MAX_ALLOWLIST_REQUEST_BYTES = 1024 * 1024

function mediaType(value) {
	if (typeof value !== "string") return ""
	return value.split(";", 1)[0].trim().toLowerCase()
}

function contentEncoding(value) {
	if (value === undefined) return "identity"
	if (Array.isArray(value)) return value.map(String).join(",").trim().toLowerCase()
	return String(value).trim().toLowerCase()
}

export function sanitizeToolLabel(value) {
	if (typeof value !== "string" || !value.length) return "<invalid>"
	return "<redacted>"
}

export function toolPolicyAudit(route, reason, toolName) {
	return {
		event: "mcp_gateway_tool_policy_denied",
		route: route.prefix,
		tool: sanitizeToolLabel(toolName),
		reason,
		outcome: "denied",
	}
}

function deny(reason, toolName) {
	return {
		allowed: false,
		status: 403,
		reason,
		toolName,
		isToolsList: false,
	}
}

export function inspectAllowlistedRequest({ method, headers, body, allowTools }) {
	if (!Array.isArray(allowTools)) {
		return { allowed: true, isToolsList: false, message: null }
	}
	if (method !== "POST") {
		return { allowed: true, isToolsList: false, message: null }
	}
	if (contentEncoding(headers["content-encoding"]) !== "identity") {
		return deny("unsupported_content_encoding")
	}
	if (mediaType(headers["content-type"]) !== "application/json") {
		return deny("unsupported_content_type")
	}
	if (!Buffer.isBuffer(body) || body.length > MAX_ALLOWLIST_REQUEST_BYTES) {
		return deny("request_too_large")
	}

	let message
	try {
		message = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body))
	} catch {
		return deny("malformed_json")
	}
	if (!message || typeof message !== "object" || Array.isArray(message)) {
		return deny(Array.isArray(message) ? "batch_not_allowed" : "invalid_jsonrpc_shape")
	}
	if (typeof message.method !== "string" || !message.method.length) {
		return deny("invalid_jsonrpc_shape")
	}
	if (message.method !== "tools/call") {
		return {
			allowed: true,
			isToolsList: message.method === "tools/list",
			message,
		}
	}
	const params = message.params
	const name = params && typeof params === "object" && !Array.isArray(params)
		? params.name
		: undefined
	if (typeof name !== "string") return deny("invalid_tool_name", name)
	if (!allowTools.includes(name)) return deny("tool_not_allowed", name)
	return { allowed: true, isToolsList: false, message }
}
