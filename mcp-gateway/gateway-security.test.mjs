import assert from "node:assert/strict"
import { test } from "node:test"

import {
	AccessModePolicyError,
	allSpawnPorts,
	parseHistoricalOffsets,
	resolveAccessMode,
} from "./spawn-policy.mjs"

const protectedRoute = {
	prefix: "ts/postgres_prod_prefect",
	spawn: {
		accessMode: "restricted",
		maxAccessMode: "restricted",
		protected: true,
		port: 8814,
	},
}

test("protected routes clamp unrestricted requests in compatibility mode", () => {
	const decision = resolveAccessMode(
		protectedRoute,
		new URL("http://localhost/sse?access_mode=unrestricted"),
		"clamp",
	)
	assert.equal(decision.accessMode, "restricted")
	assert.deepEqual(decision.audit, {
		event: "protected_access_mode_ceiling",
		route: "ts/postgres_prod_prefect",
		requested: "unrestricted",
		maximum: "restricted",
		policy: "clamp",
		outcome: "clamped",
	})
})

test("protected routes reject unrestricted requests when the flip is enabled", () => {
	assert.throws(
		() => resolveAccessMode(
			protectedRoute,
			new URL("http://localhost/sse?postgresAccessMode=unrestricted"),
			"reject",
		),
		(error) => error instanceof AccessModePolicyError && error.statusCode === 403,
	)
})

test("unprotected routes retain explicitly requested access modes", () => {
	const route = { prefix: "ts/postgres_dev", spawn: { accessMode: "unrestricted", port: 8811 } }
	assert.equal(resolveAccessMode(
		route,
		new URL("http://localhost/sse?accessMode=restricted"),
		"clamp",
	).accessMode, "restricted")
})

test("startup and reload enumerate current explicit and historical alternate ports", () => {
	const offsets = parseHistoricalOffsets(1200, "1000,1200,2000,invalid,-1")
	assert.deepEqual(offsets, [1200, 1000, 2000])
	assert.deepEqual(allSpawnPorts([
		protectedRoute,
		{ prefix: "ts/postgres_dev", spawn: {
			accessMode: "unrestricted", port: 8811, ports: { restricted: 9911 },
		} },
	], offsets), [8811, 8814, 9811, 9814, 9911, 10011, 10014, 10811, 10814])
})
