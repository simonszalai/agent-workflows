#!/usr/bin/env node
// Read-only identity canary for the project-routed AutoDEV proxy. It deliberately
// asks for a nonexistent project; a restricted bearer must pin the request back
// to the route's expected project.
import fs from "node:fs"

const routeMode = process.argv[2] === "--route"
const routesFile = routeMode ? "" : process.argv[2]
const port = Number(routeMode ? process.argv[5] || 8792 : process.argv[3] || 8792)
if ((!routeMode && !routesFile) || (routeMode && (!process.argv[3] || !process.argv[4]))) {
	console.error("usage: verify-autodev-routes.mjs <routes.json> [port]")
	console.error("   or: verify-autodev-routes.mjs --route <prefix> <project> [port]")
	process.exit(2)
}

const config = routeMode
	? { routes: [{ prefix: process.argv[3], expectedProject: process.argv[4] }] }
	: JSON.parse(fs.readFileSync(routesFile, "utf8"))
if (!Array.isArray(config.routes) || config.routes.length === 0) {
	console.error("route config has no routes")
	process.exit(2)
}

let failed = false
for (const [index, route] of config.routes.entries()) {
	if (!route.expectedProject) {
		console.error(`${route.prefix}: expectedProject is missing`)
		failed = true
		continue
	}
	let lastError = "no response"
	let verified = false
	for (let attempt = 1; attempt <= 3 && !verified; attempt += 1) {
		try {
			const response = await fetch(`http://127.0.0.1:${port}${route.prefix}/mcp`, {
				method: "POST",
				headers: {
					"content-type": "application/json",
					accept: "application/json, text/event-stream",
				},
				body: JSON.stringify({
					jsonrpc: "2.0",
					id: index + 1,
					method: "tools/call",
					params: {
						name: "get_project",
						arguments: { project_name: "__proxy_route_identity_canary__" },
					},
				}),
				signal: AbortSignal.timeout(15_000),
			})
			if (!response.ok) {
				lastError = `HTTP ${response.status}`
			} else {
				const payload = await response.json()
				const project = payload?.result?.structuredContent?.project_name
				if (project === route.expectedProject) {
					console.log(`${route.prefix}: pinned to ${project}`)
					verified = true
				} else {
					lastError = `expected ${route.expectedProject}, got ${project || "no project identity"}`
				}
			}
		} catch (error) {
			lastError = error.message || String(error)
		}
		if (!verified && attempt < 3) await new Promise((resolve) => setTimeout(resolve, 2_000))
	}
	if (!verified) {
		console.error(`${route.prefix}: ${lastError}`)
		failed = true
	}
}

if (failed) process.exit(1)
