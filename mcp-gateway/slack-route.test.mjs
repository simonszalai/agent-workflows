import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

import { BASE_DIR, loadRoutes } from "./lib/config.mjs"

test("shared Slack route uses the official server and a gateway-owned token", () => {
	const route = loadRoutes().find((candidate) => candidate.prefix === "shared/slack")
	assert.ok(route)
	assert.equal(route.target, "https://mcp.slack.com/mcp")
	assert.equal(route.authEnv, "SLACK_MCP_USER_TOKEN")
	assert.equal(route.authHeader, undefined)
	assert.equal(route.authScheme, undefined)
})

test("Slack credentials are loaded once from 1Password, never committed", () => {
	const env = readFileSync(`${BASE_DIR}/gateway.env`, "utf8")
	assert.match(env, /^SLACK_MCP_USER_TOKEN=op:\/\/MCP\/SLACK_MCP_USER_TOKEN\/value$/m)
	assert.doesNotMatch(env, /xox[pbar]-[A-Za-z0-9-]+/)
})

test("Slack app manifest is read-only", () => {
	const manifest = readFileSync(`${BASE_DIR}/slack-app-manifest.yaml`, "utf8")
	assert.match(manifest, /search:read\.im/)
	assert.match(manifest, /im:history/)
	assert.doesNotMatch(manifest, /\bfiles:read\b/)
	assert.doesNotMatch(manifest, /\bchat:write\b/)
	assert.doesNotMatch(manifest, /\bchannels:write\b/)
})
