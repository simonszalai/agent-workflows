import assert from "node:assert/strict"
import { test } from "node:test"

import { buildSpawnCommand, reapPatternFor } from "./lib/supervisor.mjs"

const genericRoute = {
	prefix: "ts/tailscale",
	spawn: {
		kind: "generic",
		bin: "/usr/local/bin/npx",
		args: ["-y", "--package=@x/y", "y-server", "--http", "--port", "8855", "--host", "127.0.0.1"],
		port: 8855,
		reapPattern: "y-server.*--port 8855 ",
		env: { MCP_HTTP_BEARER_TOKEN: "${TEST_SUP_TOKEN}", STATIC_VALUE: "-" },
	},
}

const dbhubRoute = {
	prefix: "ts/postgres",
	spawn: { kind: "dbhub", config: "dbhub/ts.toml", port: 8851, bin: "/usr/local/bin/dbhub" },
}

test("generic spawn takes argv verbatim and interpolates ${VAR} env from the daemon env", () => {
	process.env.TEST_SUP_TOKEN = "tok-123"
	const { bin, args, env } = buildSpawnCommand(genericRoute)
	assert.equal(bin, "/usr/local/bin/npx")
	assert.deepEqual(args, genericRoute.spawn.args)
	assert.equal(env.MCP_HTTP_BEARER_TOKEN, "tok-123")
	assert.equal(env.STATIC_VALUE, "-")
	// Secrets must never leak into argv.
	assert.ok(!args.some((a) => a.includes("tok-123")))
	delete process.env.TEST_SUP_TOKEN
})

test("generic spawn env inherits the daemon env (route secrets arrive by inheritance)", () => {
	process.env.TEST_SUP_INHERITED = "inherited-value"
	const { env } = buildSpawnCommand(genericRoute)
	assert.equal(env.TEST_SUP_INHERITED, "inherited-value")
	delete process.env.TEST_SUP_INHERITED
})

test("dbhub spawn keeps its fixed arg template", () => {
	const { bin, args } = buildSpawnCommand(dbhubRoute)
	assert.equal(bin, "/usr/local/bin/dbhub")
	assert.deepEqual(args.slice(0, 6), ["--transport", "http", "--host", "127.0.0.1", "--port", "8851"])
	assert.equal(args[6], "--config")
	assert.ok(args[7].endsWith("dbhub/ts.toml"))
})

test("reap patterns anchor the port with a trailing space", () => {
	assert.equal(reapPatternFor(dbhubRoute.spawn), "dbhub.*--port 8851 ")
	assert.equal(reapPatternFor(genericRoute.spawn), "y-server.*--port 8855 ")
	assert.ok(reapPatternFor(genericRoute.spawn).endsWith(" "))
})
