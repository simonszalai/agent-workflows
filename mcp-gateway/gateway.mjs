#!/usr/bin/env node
// mcp-gateway — one local daemon that fronts all remote MCP servers for every
// workspace/session, so clients (Claude Code / Cursor / Codex) connect over native
// `type: http` to 127.0.0.1 instead of each spawning its own `mcp-remote` child.
//
// Why this exists: each workspace × server × session used to exec a separate
// `mcp-remote` stdio bridge (~60 node procs observed), and N bridges hammering the
// single small autodev-memory instance starved it (writes hung). This daemon replaces
// all of them: ONE process, secrets loaded ONCE (start-gateway.sh resolves 1Password
// refs in a single `op run`), upstream TCP pooled, and project identity carried in the
// URL path so project-scoped servers (render, postgres) route to the right creds.
//
// Layout:
//   lib/config.mjs           routes.json loading + `--validate` preflight
//   lib/proxy.mjs            the transparent streaming reverse proxy (retry, auth swap)
//   lib/supervisor.mjs       locally-spawned dbhub children (postgres, Streamable HTTP)
//   lib/render-preflight.mjs auto-select the Render workspace per MCP session
//   waf-encode.mjs           encode autodev-memory writes past Render's edge WAF
//
// Config URLs look like http://127.0.0.1:8765/<project>/<server>[/mcp].
// Secrets come from process.env only — never from this repo's files.
//
// Run `node gateway.mjs --validate` before restarting the daemon: every restart costs a
// Touch ID prompt, so config problems (stale op:// refs, missing env, bad ports) must be
// caught without one.
import http from "node:http"
import { HOST, PORT, LOCAL_TOKEN, loadRoutes, validate } from "./lib/config.mjs"
import { log } from "./lib/log.mjs"
import { createRequestHandler } from "./lib/proxy.mjs"
import { startAll, startNew, stopAll } from "./lib/supervisor.mjs"

if (process.argv.includes("--validate")) {
	const problems = validate()
	if (problems.length) {
		for (const p of problems) console.error("INVALID:", p)
		process.exit(1)
	}
	console.log(`config OK: ${loadRoutes().length} routes`)
	process.exit(0)
}

let routes = loadRoutes()
for (const p of validate()) log("config warning:", p)

const server = http.createServer(createRequestHandler(() => routes))

server.listen(PORT, HOST, () => {
	log(`mcp-gateway listening on http://${HOST}:${PORT}`)
	log(`routes: ${routes.map((r) => r.prefix).join(", ")}`)
	log(`local auth: ${LOCAL_TOKEN ? "required (x-mcp-gateway-token)" : "off (localhost only)"}`)
	startAll(routes)
})

// SIGHUP reloads routes.json without dropping the listener / pooled sockets. Additive
// for spawn routes: new children start, running ones are left in place so a reload
// never drops live MCP sessions.
process.on("SIGHUP", () => {
	try {
		routes = loadRoutes()
		startNew(routes)
		log("reloaded routes:", routes.map((r) => r.prefix).join(", "))
	} catch (e) {
		log("route reload failed:", String(e.message || e))
	}
})

// Kill daemon-owned children on shutdown so a launchd unload tears the whole tree down
// (no orphaned dbhub servers). Exit 128+signum (NOT 0) so launchd's
// KeepAlive(SuccessfulExit=false) still auto-restarts after an external kill; a real
// `launchctl unload` removes the job (no restart) and system shutdown won't restart either.
function shutdown(sig) {
	const signum = sig === "SIGINT" ? 2 : 15
	const n = stopAll()
	log(`received ${sig}; stopping ${n} child(ren) and exiting`)
	setTimeout(() => process.exit(128 + signum), 1500).unref()
}
process.on("SIGTERM", () => shutdown("SIGTERM"))
process.on("SIGINT", () => shutdown("SIGINT"))
