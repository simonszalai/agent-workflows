export const ACCESS_MODES = new Set(["restricted", "unrestricted"])
export const ACCESS_MODE_RANK = { restricted: 0, unrestricted: 1 }
export const PROTECTED_POLICY_MODES = new Set(["clamp", "reject"])

export class AccessModePolicyError extends Error {
	constructor(message, statusCode = 403, audit = null) {
		super(message)
		this.name = "AccessModePolicyError"
		this.statusCode = statusCode
		this.audit = audit
	}
}

export function defaultAccessMode(route) {
	return route.spawn?.accessMode || "restricted"
}

export function maxAccessMode(route) {
	return route.spawn?.maxAccessMode || (route.spawn?.protected ? "restricted" : "unrestricted")
}

export function exceedsAccessModeCeiling(route, accessMode) {
	return ACCESS_MODE_RANK[accessMode] > ACCESS_MODE_RANK[maxAccessMode(route)]
}

export function parseAccessMode(url) {
	return (
		url.searchParams.get("access_mode") ||
		url.searchParams.get("accessMode") ||
		url.searchParams.get("postgres_access_mode") ||
		url.searchParams.get("postgresAccessMode") ||
		""
	).trim().toLowerCase()
}

export function resolveAccessMode(route, url, policyMode = "clamp") {
	if (!route.spawn) return { accessMode: null, audit: null }
	if (!PROTECTED_POLICY_MODES.has(policyMode)) {
		throw new AccessModePolicyError(
			`invalid protected access-mode policy=${policyMode}; expected clamp or reject`,
			500,
		)
	}
	const requested = parseAccessMode(url) || defaultAccessMode(route)
	if (!ACCESS_MODES.has(requested)) {
		throw new AccessModePolicyError(
			`invalid access_mode=${requested}; expected restricted or unrestricted`,
			400,
		)
	}
	if (!exceedsAccessModeCeiling(route, requested)) {
		return { accessMode: requested, audit: null }
	}
	const audit = {
		event: "protected_access_mode_ceiling",
		route: route.prefix,
		requested,
		maximum: maxAccessMode(route),
		policy: policyMode,
		outcome: policyMode === "clamp" ? "clamped" : "rejected",
	}
	if (policyMode === "reject") {
		throw new AccessModePolicyError(
			`access_mode=${requested} exceeds maximum=${audit.maximum} for protected route ${route.prefix}`,
			403,
			audit,
		)
	}
	return { accessMode: audit.maximum, audit }
}

export function parseHistoricalOffsets(currentOffset, rawHistorical = "1000") {
	const values = [currentOffset, ...String(rawHistorical).split(",")]
	return [...new Set(values.map(Number).filter((value) => Number.isInteger(value) && value > 0))]
}

export function routePorts(route, offsets) {
	if (!route.spawn) return []
	const ports = [route.spawn.port]
	for (const port of Object.values(route.spawn.ports || {})) ports.push(Number(port))
	for (const offset of offsets) ports.push(route.spawn.port + offset)
	return [...new Set(ports.filter((port) => Number.isInteger(port) && port > 0 && port <= 65535))]
}

export function allSpawnPorts(routes, offsets) {
	return [...new Set(routes.flatMap((route) => routePorts(route, offsets)))].sort((a, b) => a - b)
}
