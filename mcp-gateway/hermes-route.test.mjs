import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

import { BASE_DIR, loadRoutes } from "./lib/config.mjs"

const AUTODEV_TOOLS = [
	"create_artifact",
	"create_ticket",
	"expand_entries",
	"get_all_tags",
	"get_artifact",
	"get_artifact_history",
	"get_entry",
	"get_project",
	"get_repo",
	"get_review_patterns",
	"get_security_config_summary",
	"get_similar_tickets",
	"get_stats",
	"get_ticket",
	"get_ticket_contexts",
	"list_artifact_comments",
	"list_entries",
	"list_projects",
	"list_repos",
	"list_tickets",
	"next_ticket",
	"reply_artifact_comment",
	"search",
	"search_tickets",
	"update_artifact",
	"update_ticket",
]

const RENDER_TOOLS = [
	"get_deploy",
	"get_key_value",
	"get_metrics",
	"get_postgres",
	"get_selected_workspace",
	"get_service",
	"list_deploys",
	"list_key_value",
	"list_log_label_values",
	"list_logs",
	"list_postgres_instances",
	"list_services",
	"list_workspaces",
]

const SLACK_TOOLS = [
	"slack_add_reaction",
	"slack_get_reactions",
	"slack_list_channel_members",
	"slack_read_channel",
	"slack_read_thread",
	"slack_read_user_profile",
	"slack_search_channels",
	"slack_search_emojis",
	"slack_search_public",
	"slack_search_public_and_private",
	"slack_search_users",
	"slack_send_message",
]

function byPrefix(routes, prefix) {
	const route = routes.find((candidate) => candidate.prefix === prefix)
	assert.ok(route, `missing route ${prefix}`)
	return route
}

function documentedInventory(readme, prefix) {
	const verbs = {
		"hermes/autodev-memory": "uses",
		"hermes/render": "reuses",
		"hermes/slack": "permits",
	}
	const sectionStart = readme.indexOf(`\`${prefix}\` ${verbs[prefix]}`)
	assert.notEqual(sectionStart, -1, `missing README section for ${prefix}`)
	const blockStart = readme.indexOf("```text\n", sectionStart)
	assert.notEqual(blockStart, -1, `missing README inventory for ${prefix}`)
	const contentStart = blockStart + "```text\n".length
	const blockEnd = readme.indexOf("\n```", contentStart)
	assert.notEqual(blockEnd, -1, `unterminated README inventory for ${prefix}`)
	return readme.slice(contentStart, blockEnd).split("\n")
}

test("the three Hermes routes clone the intended upstream identities", () => {
	const routes = loadRoutes()
	const sharedMemory = byPrefix(routes, "shared/autodev-memory")
	const sharedSlack = byPrefix(routes, "shared/slack")
	const tsRender = byPrefix(routes, "ts/render")
	const memory = byPrefix(routes, "hermes/autodev-memory")
	const render = byPrefix(routes, "hermes/render")
	const slack = byPrefix(routes, "hermes/slack")

	assert.equal(memory.target, sharedMemory.target)
	assert.equal(memory.authEnv, "HERMES_AUTODEV_MEMORY_TOKEN")
	assert.equal(render.target, tsRender.target)
	assert.equal(render.authEnv, tsRender.authEnv)
	assert.equal(render.renderWorkspace, tsRender.renderWorkspace)
	assert.equal(slack.target, sharedSlack.target)
	assert.equal(slack.authEnv, sharedSlack.authEnv)
	for (const route of [memory, render, slack]) {
		assert.equal(route.clientTokenEnv, "HERMES_GATEWAY_TOKEN")
	}
})

test("Hermes allowTools inventories are exact, unique positive lists", () => {
	const routes = loadRoutes()
	assert.deepEqual(byPrefix(routes, "hermes/autodev-memory").allowTools, AUTODEV_TOOLS)
	assert.deepEqual(byPrefix(routes, "hermes/render").allowTools, RENDER_TOOLS)
	assert.deepEqual(byPrefix(routes, "hermes/slack").allowTools, SLACK_TOOLS)
	for (const tools of [AUTODEV_TOOLS, RENDER_TOOLS, SLACK_TOOLS]) {
		assert.equal(new Set(tools).size, tools.length)
		assert.ok(tools.every((name) => typeof name === "string" && name.length > 0))
	}
})

test("destructive, approval, epic, deploy, file, and admin families stay absent", () => {
	for (const forbidden of [
		"delete_artifact",
		"delete_entry",
		"approve_execution",
		"create_epic",
		"get_epic",
		"merge_entries",
		"supersede_entry",
		"update_project",
	]) {
		assert.ok(!AUTODEV_TOOLS.includes(forbidden), forbidden)
	}
	for (const forbidden of [
		"create_service",
		"trigger_deploy",
		"update_environment_variables",
		"select_workspace",
		"query_render_postgres",
	]) {
		assert.ok(!RENDER_TOOLS.includes(forbidden), forbidden)
	}
	for (const forbidden of [
		"slack_create_canvas",
		"slack_create_conversation",
		"slack_read_file",
		"slack_schedule_message",
		"slack_send_draft",
	]) {
		assert.ok(!SLACK_TOOLS.includes(forbidden), forbidden)
	}
})

test("trusted routes remain unrestricted in the checked-in JSON", () => {
	const raw = JSON.parse(readFileSync(`${BASE_DIR}/routes.json`, "utf8")).routes
	for (const prefix of ["shared/autodev-memory", "shared/context7", "shared/slack", "ts/render"]) {
		assert.equal(raw[prefix].clientTokenEnv, undefined)
		assert.equal(raw[prefix].allowTools, undefined)
	}
})

test("README records disabled-by-absence and the M2/M3 ownership boundary", () => {
	const readme = readFileSync(`${BASE_DIR}/README.md`, "utf8")
	assert.match(readme, /Omitting `allowTools` means unrestricted/)
	assert.match(readme, /unset non-default `clientTokenEnv` disables that route with 503/)
	assert.match(readme, /never falls back to `MCP_GATEWAY_TOKEN`/)
	assert.match(readme, /never start at daemon startup or reload/)
	assert.match(readme, /`tools\/call` is the security boundary/)
	assert.match(readme, /`tools\/list` filtering is defense in depth/)
	assert.match(readme, /F0021 owns\s+secret provisioning and the full runtime reload/)
	assert.match(readme, /F0022 owns real Hermes client wiring/)
	assert.deepEqual(documentedInventory(readme, "hermes/autodev-memory"), AUTODEV_TOOLS)
	assert.deepEqual(documentedInventory(readme, "hermes/render"), RENDER_TOOLS)
	assert.deepEqual(documentedInventory(readme, "hermes/slack"), SLACK_TOOLS)
})

test("the Slack manifest remains message and reaction scoped without expansion", () => {
	const manifest = readFileSync(`${BASE_DIR}/slack-app-manifest.yaml`, "utf8")
	assert.match(manifest, /\bchat:write\b/)
	assert.match(manifest, /\breactions:write\b/)
	assert.doesNotMatch(manifest, /\bfiles:read\b/)
	assert.doesNotMatch(manifest, /\bchannels:write\b/)
	assert.doesNotMatch(manifest, /\badmin\b/)
})
