// Configuration: listener settings and the routing table (routes.json).
//
// Routes map a path prefix "<project>/<server>" (or "shared/<server>") to either
//   (1) a remote HTTP upstream: { target, authEnv, authHeader?, authScheme?, renderWorkspace? }
//       — tokens live in env vars (loaded once by start-gateway.sh), never in routes.json; or
//   (2) a supervised local child: { spawn: { kind: "dbhub", config, port, bin? } }
//       — the daemon launches one long-lived dbhub per entry on 127.0.0.1:<port> and
//       proxies to it; `target` is derived. DB DSNs come from ${ENV_VAR} interpolation
//       inside the dbhub TOML (see dbhub/*.toml), so they stay out of argv and this file.
import { readFileSync, existsSync, accessSync, constants } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

export const BASE_DIR = dirname(dirname(fileURLToPath(import.meta.url)))

export const HOST = process.env.MCP_GATEWAY_HOST || "127.0.0.1"
export const PORT = Number(process.env.MCP_GATEWAY_PORT || 8765)
// Shared secret so only configured clients can use the daemon's upstream credentials.
// The 127.0.0.1 bind alone doesn't stop browser-borne requests (DNS rebinding), so
// clients must send x-mcp-gateway-token. Empty = no local auth.
export const LOCAL_TOKEN = process.env.MCP_GATEWAY_TOKEN || ""

const READONLY_SOURCES = {
	"dbhub/ts.toml": ["prod", "prod_prefect", "autodev_ts"],
	"dbhub/amaru.toml": ["prod"],
	"dbhub/workflow.toml": ["prod"],
	"dbhub/shared.toml": ["autodev_global"],
}

function readonlyExecuteSql(toml, source) {
	return toml.split("[[tools]]").slice(1).some((block) =>
		/^\s*name\s*=\s*["']execute_sql["']/m.test(block) &&
		new RegExp(`^\\s*source\\s*=\\s*["']${source}["']`, "m").test(block) &&
		/^\s*readonly\s*=\s*true\s*$/m.test(block),
	)
}

export function loadRoutes() {
	const raw = JSON.parse(readFileSync(join(BASE_DIR, "routes.json"), "utf8"))
	// Sort prefixes longest-first so the most specific route wins.
	// Keys starting with "_" are comments, not routes.
	return Object.entries(raw.routes)
		.filter(([prefix]) => !prefix.startsWith("_"))
		.map(([prefix, def]) => {
			const r = { prefix: prefix.replace(/^\/|\/$/g, ""), ...def }
			// Spawn routes proxy to the loopback port their child binds.
			if (r.spawn && !r.target) r.target = `http://127.0.0.1:${r.spawn.port}`
			return r
		})
		.sort((a, b) => b.prefix.length - a.prefix.length)
}

// Preflight the whole config chain: routes.json shape, spawn binaries/configs on disk,
// TOML ${ENV_VAR} interpolations resolvable, auth env vars set. Returns a list of
// problem strings (empty = healthy). Run via `node gateway.mjs --validate` BEFORE a
// daemon restart — every restart costs a Touch ID prompt, so failures must be caught here.
export function validate() {
	const problems = []
	let routes
	try {
		routes = loadRoutes()
	} catch (e) {
		return [`routes.json unreadable: ${String(e.message || e)}`]
	}
	const ports = new Map()
	for (const r of routes) {
		if (r.spawn) {
			const s = r.spawn
			if (s.kind !== "dbhub") problems.push(`${r.prefix}: unknown spawn kind '${s.kind}'`)
			if (!s.port) problems.push(`${r.prefix}: spawn.port missing`)
			else if (ports.has(s.port)) problems.push(`${r.prefix}: port ${s.port} already used by ${ports.get(s.port)}`)
			else ports.set(s.port, r.prefix)
			const bin = s.bin || process.env.DBHUB_BIN || "dbhub"
			if (bin.includes("/")) {
				try { accessSync(bin, constants.X_OK) } catch { problems.push(`${r.prefix}: spawn.bin not executable: ${bin}`) }
			}
			if (!s.config) {
				problems.push(`${r.prefix}: spawn.config missing`)
			} else {
				const cfg = join(BASE_DIR, s.config)
				if (!existsSync(cfg)) {
					problems.push(`${r.prefix}: config not found: ${cfg}`)
				} else {
					// Every ${VAR} the TOML interpolates must be exported by start-gateway.sh.
					const toml = readFileSync(cfg, "utf8")
					for (const [, v] of toml.matchAll(/\$\{([A-Z0-9_]+)\}/g)) {
						if (!process.env[v]) problems.push(`${r.prefix}: env ${v} (used by ${s.config}) is unset`)
					}
					for (const source of READONLY_SOURCES[s.config] || []) {
						if (!readonlyExecuteSql(toml, source)) {
							problems.push(`${r.prefix}: execute_sql source '${source}' must set readonly=true`)
						}
					}
				}
			}
		} else {
			if (!r.target) problems.push(`${r.prefix}: no target and no spawn`)
			if (r.authEnv && !process.env[r.authEnv]) problems.push(`${r.prefix}: env ${r.authEnv} is unset`)
		}
	}
	return problems
}
