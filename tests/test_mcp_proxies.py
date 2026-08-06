from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXIES = ROOT / "mcp-proxies"


class McpProxyConfigurationTest(unittest.TestCase):
    def test_mac_routes_match_every_registered_project_profile(self) -> None:
        registry = json.loads((ROOT / "config/project-tools.json").read_text())
        routes = json.loads((PROXIES / "autodev-routes.json").read_text())["routes"]
        by_project = {route["expectedProject"]: route for route in routes}

        expected = {}
        for project, profile in registry["projects"].items():
            memory = profile["autodev_memory"]
            server_project = project.replace("-", "_")
            expected[server_project] = {
                "prefix": f"/{memory['route']}",
                "token_ref": memory["token_ref"],
            }
        self.assertEqual(set(by_project), set(expected))

        refs = {}
        for raw in (PROXIES / "autodev-routes.env").read_text().splitlines():
            if raw and not raw.startswith("#"):
                name, ref = raw.split("=", 1)
                refs[name] = ref
        for server_project, wanted in expected.items():
            route = by_project[server_project]
            self.assertEqual(route["prefix"], wanted["prefix"])
            self.assertEqual(refs[route["authEnv"]], wanted["token_ref"])
            self.assertTrue(route["transformBody"])

    def test_mac_launcher_uses_one_shot_project_credentials_without_op_parents(self) -> None:
        script = (PROXIES / "start-proxies.sh").read_text()
        self.assertNotRegex(script, re.compile(r"^\s*op\s+run\b", re.M))
        self.assertIn('op read --no-newline "$ref"', script)
        for item in ("op-amaru-token", "op-autodev-token", "op-ts-token", "op-workflow-pro-token"):
            self.assertIn(item, script)
        self.assertIn("unset OP_SERVICE_ACCOUNT_TOKEN OP_CONNECT_TOKEN", script)

    def test_cloud_launcher_selects_exact_repo_and_strips_service_account(self) -> None:
        script = (PROXIES / "start-cloud-proxies.sh").read_text()
        self.assertIn('--cwd "$REPO_DIR" --tool autodev_memory', script)
        self.assertIn('MCP_PROXY_PREFIX="/${ROUTE}"', script)
        self.assertIn('env -u "$TOKEN_ENV" -u OP_SERVICE_ACCOUNT_TOKEN -u OP_CONNECT_TOKEN', script)
        self.assertNotRegex(script, re.compile(r"\bop\s+run\b"))
        self.assertIn('op read --no-newline "$TOKEN_REF"', script)


if __name__ == "__main__":
    unittest.main()
