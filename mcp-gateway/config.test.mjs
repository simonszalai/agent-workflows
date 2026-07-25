import assert from "node:assert/strict"
import { test } from "node:test"

import {
	DEFAULT_CLIENT_TOKEN_ENV,
	normalizeRoutes,
	validateRoutes,
} from "./lib/config.mjs"

function routes(definitions) {
	return normalizeRoutes({ routes: definitions })
}

test("malformed routing table shapes are rejected", () => {
	for (const raw of [
		null,
		[],
		{},
		{ routes: null },
		{ routes: [] },
	]) {
		assert.throws(() => normalizeRoutes(raw), /routes must be an object/)
	}
})

test("clientTokenEnv defaults while explicit route policy remains unchanged", () => {
	const loaded = routes({
		"shared/read": { target: "https://example.test/mcp" },
		"hermes/read": {
			target: "https://example.test/mcp",
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			allowTools: ["get_ticket", "search"],
		},
	})
	assert.equal(loaded.find((route) => route.prefix === "shared/read").clientTokenEnv,
		DEFAULT_CLIENT_TOKEN_ENV)
	assert.deepEqual(loaded.find((route) => route.prefix === "hermes/read").allowTools,
		["get_ticket", "search"])
})

test("allowTools accepts only a positive unique inventory", () => {
	const cases = [
		[[], /must not be empty/],
		["search", /must be a non-empty array/],
		[["search", "search"], /duplicate allowTools/],
		[[""], /non-empty strings without surrounding whitespace/],
		[["   "], /non-empty strings without surrounding whitespace/],
		[[" search"], /non-empty strings without surrounding whitespace/],
		[["search "], /non-empty strings without surrounding whitespace/],
		[["search", 1], /non-empty strings without surrounding whitespace/],
	]
	for (const [allowTools, expected] of cases) {
		const problems = validateRoutes(routes({
			"hermes/test": {
				target: "https://example.test/mcp",
				clientTokenEnv: "HERMES_GATEWAY_TOKEN",
				allowTools,
			},
		}), {})
		assert.ok(problems.some((problem) => expected.test(problem)), JSON.stringify(problems))
	}
})

test("malformed clientTokenEnv and allowTools without a destination fail validation", () => {
	for (const clientTokenEnv of ["", " ", 12, "lower-case"]) {
		const problems = validateRoutes(routes({
			"hermes/test": { target: "https://example.test/mcp", clientTokenEnv },
		}), {})
		assert.ok(problems.some((problem) => problem.includes("clientTokenEnv")))
	}
	const noDestination = validateRoutes(routes({
		"hermes/test": {
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			allowTools: ["search"],
		},
	}), {})
	assert.ok(noDestination.some((problem) => problem.includes("allowTools requires")))
	assert.ok(noDestination.some((problem) => problem.includes("no target and no spawn")))
})

test("an unset explicit client token safely disables its missing upstream credential", () => {
	const hermes = routes({
		"hermes/test": {
			target: "https://example.test/mcp",
			authEnv: "HERMES_UPSTREAM_TOKEN",
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			allowTools: ["search"],
		},
	})
	assert.deepEqual(validateRoutes(hermes, {}), [])

	const shared = routes({
		"shared/test": {
			target: "https://example.test/mcp",
			authEnv: "SHARED_UPSTREAM_TOKEN",
		},
	})
	assert.ok(validateRoutes(shared, {}).some((problem) =>
		problem.includes("SHARED_UPSTREAM_TOKEN is unset")))
})

test("an unset explicit client token skips runtime-only spawn credential checks", () => {
	const protectedSpawn = routes({
		"hermes/spawn": {
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
			authEnv: "HERMES_UPSTREAM_TOKEN",
			allowTools: ["search"],
			spawn: {
				kind: "generic",
				bin: process.execPath,
				args: ["fake-server", "--port", "8899", "--host", "127.0.0.1"],
				port: 8899,
				reapPattern: "fake-server.*--port 8899 ",
				env: { CHILD_TOKEN: "${HERMES_CHILD_TOKEN}" },
				requiresEnv: ["HERMES_INHERITED_TOKEN"],
			},
		},
	})
	assert.deepEqual(validateRoutes(protectedSpawn, {}), [])

	const activeProblems = validateRoutes(protectedSpawn, {
		HERMES_GATEWAY_TOKEN: "synthetic-client-token",
	})
	for (const name of [
		"HERMES_UPSTREAM_TOKEN",
		"HERMES_CHILD_TOKEN",
		"HERMES_INHERITED_TOKEN",
	]) {
		assert.ok(activeProblems.some((problem) => problem.includes(name)), name)
	}
})

test("distinct client env names cannot resolve to the same token value", () => {
	const collisionCanary = "synthetic-collision-canary"
	const loaded = routes({
		"one/test": {
			target: "https://example.test/mcp",
			clientTokenEnv: "FIRST_CLIENT_TOKEN",
		},
		"two/test": {
			target: "https://example.test/mcp",
			clientTokenEnv: "SECOND_CLIENT_TOKEN",
		},
	})
	const problems = validateRoutes(loaded, {
		FIRST_CLIENT_TOKEN: collisionCanary,
		SECOND_CLIENT_TOKEN: collisionCanary,
	})
	assert.ok(problems.some((problem) =>
		problem.includes("FIRST_CLIENT_TOKEN and SECOND_CLIENT_TOKEN")))
	assert.ok(problems.every((problem) => !problem.includes(collisionCanary)))
})

test("routes may share one client env name without a collision", () => {
	const loaded = routes({
		"hermes/one": {
			target: "https://example.test/mcp",
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
		},
		"hermes/two": {
			target: "https://example.test/mcp",
			clientTokenEnv: "HERMES_GATEWAY_TOKEN",
		},
	})
	assert.deepEqual(validateRoutes(loaded, { HERMES_GATEWAY_TOKEN: "synthetic" }), [])
})
