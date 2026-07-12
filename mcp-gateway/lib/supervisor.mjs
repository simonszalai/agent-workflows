// Supervision of locally-spawned MCP children (dbhub, Streamable HTTP).
//
// The daemon owns one long-lived dbhub process per spawn route: secrets are resolved
// once at daemon start, children die with the daemon (no orphans), and each project's
// DB connections are shared across every workspace's sessions instead of one child per
// session. Desired state lives in routes.json; running state lives in `children`;
// ensureRunning() reconciles the two on demand.
import { spawn, execFileSync } from "node:child_process"
import { join } from "node:path"
import { BASE_DIR } from "./config.mjs"
import { log } from "./log.mjs"

// prefix -> { proc, port, restarts, aliveTimer }
const children = new Map()
let shuttingDown = false

// A child can die without its 'exit' event ever reaching us (observed 2026-07-12 after a
// pkill bounce: exitCode stayed null, pid gone, route wedged on a corpse). Trust the map
// only if the OS confirms the pid (signal 0 probes without killing).
function procLooksAlive(entry) {
	if (!entry?.proc || entry.proc.exitCode !== null) return false
	try {
		process.kill(entry.proc.pid, 0)
		return true
	} catch {
		return false
	}
}

// Reap stray children from a previously-crashed daemon so their ports are free. The
// pattern anchors the port with a TRAILING SPACE (macOS pgrep is BSD ERE — no \b; our
// argv always has another flag after --port), so 8851 never matches 88510 and we never
// touch unrelated processes.
function reapStrays(ports) {
	for (const port of ports) {
		let out = ""
		try {
			out = execFileSync("pgrep", ["-f", `dbhub.*--port ${port} `], { encoding: "utf8" })
		} catch {
			continue // pgrep exits non-zero when nothing matches
		}
		for (const pid of out.split("\n").map((s) => s.trim()).filter(Boolean)) {
			try {
				process.kill(Number(pid), "SIGTERM")
				log(`reaped stray dbhub pid=${pid} (:${port})`)
			} catch {}
		}
	}
}

function start(route) {
	const s = route.spawn
	const key = route.prefix
	const existing = children.get(key)
	if (procLooksAlive(existing)) return existing
	reapStrays([s.port])

	// dbhub is an npm bin script (`#!/usr/bin/env node`); the launchd PATH has no node,
	// so prepend the directory of the node running this daemon.
	const bin = s.bin || process.env.DBHUB_BIN || "dbhub"
	const args = ["--transport", "http", "--host", "127.0.0.1", "--port", String(s.port), "--config", join(BASE_DIR, s.config)]
	const env = { ...process.env, PATH: `${join(process.execPath, "..")}:${process.env.PATH || ""}` }
	const proc = spawn(bin, args, { env, stdio: ["ignore", "pipe", "pipe"] })

	const entry = children.get(key) || { restarts: 0 }
	entry.proc = proc
	entry.port = s.port
	children.set(key, entry)

	const tag = `[${key}]`
	proc.stdout.on("data", (d) => log(tag, String(d).trimEnd()))
	proc.stderr.on("data", (d) => log(tag, String(d).trimEnd()))
	// Reset the restart counter once a child has been stable for a minute, so an
	// occasional crash much later doesn't inherit a long backoff.
	entry.aliveTimer = setTimeout(() => { entry.restarts = 0 }, 60_000)

	proc.on("exit", (code, sig) => {
		clearTimeout(entry.aliveTimer)
		if (shuttingDown) return
		const backoff = Math.min(30_000, 500 * 2 ** entry.restarts)
		entry.restarts += 1
		log(`spawn ${key} exited (code=${code} sig=${sig}); respawning in ${backoff}ms`)
		// Re-resolve the route from the CURRENT map entry's key at fire time; the captured
		// `route` is fine for bin/config (SIGHUP additions never mutate existing routes),
		// and ensureRunning() from live traffic also recovers a dead child.
		setTimeout(() => { if (!shuttingDown) start(route) }, backoff)
	})
	proc.on("error", (err) => {
		// Spawn failure (e.g. ENOENT bin) emits 'error' but never 'exit'; drop the entry
		// so the route isn't wedged — the next request or SIGHUP retries it.
		clearTimeout(entry.aliveTimer)
		if (children.get(key) === entry) children.delete(key)
		log(`spawn ${key} failed: ${String(err.message || err)}`)
	})
	log(`spawned ${key} -> dbhub http 127.0.0.1:${s.port}`)
	return entry
}

// Called per-request for spawn routes: returns a live entry, restarting the child if the
// map is stale. Null only if the spawn itself immediately fails.
export function ensureRunning(route) {
	const existing = children.get(route.prefix)
	if (procLooksAlive(existing)) return existing
	if (existing) children.delete(route.prefix)
	return start(route)
}

export function startAll(routes) {
	const spawnRoutes = routes.filter((r) => r.spawn)
	if (!spawnRoutes.length) return
	reapStrays(spawnRoutes.map((r) => r.spawn.port))
	for (const r of spawnRoutes) start(r)
}

// SIGHUP is additive: start children for newly-added routes, leave running ones alone
// (a reload never drops live MCP sessions). Removing a route stops proxying to its
// child immediately but the process itself lingers until the next daemon restart.
export function startNew(routes) {
	const fresh = routes.filter((r) => r.spawn && !children.has(r.prefix))
	if (!fresh.length) return
	reapStrays(fresh.map((r) => r.spawn.port))
	for (const r of fresh) start(r)
}

export function stopAll() {
	shuttingDown = true
	for (const { proc } of children.values()) {
		try { proc.kill("SIGTERM") } catch {}
	}
	return children.size
}

export function healthSnapshot() {
	return [...children.entries()].map(([key, e]) => ({
		key,
		port: e.port,
		pid: e.proc?.pid ?? null,
		alive: procLooksAlive(e),
	}))
}
