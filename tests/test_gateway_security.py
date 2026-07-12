from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GatewaySecurityTest(unittest.TestCase):
    def test_dbhub_production_sources_are_readonly(self) -> None:
        expected = {
            "ts.toml": ("prod", "prod_prefect", "autodev_ts"),
            "amaru.toml": ("prod",),
            "workflow.toml": ("prod",),
            "shared.toml": ("autodev_global",),
        }
        for filename, sources in expected.items():
            text = (ROOT / "mcp-gateway" / "dbhub" / filename).read_text()
            blocks = text.split("[[tools]]")[1:]
            for source in sources:
                matching = [block for block in blocks
                            if 'name = "execute_sql"' in block
                            and f'source = "{source}"' in block]
                self.assertEqual(len(matching), 1, f"{filename}:{source}")
                self.assertIn("readonly = true", matching[0], f"{filename}:{source}")

    def test_project_mcp_protected_fallbacks_use_restricted_guard(self) -> None:
        source = (ROOT / "bin/project-mcp").read_text()
        for route in (
            "shared:postgres_autodev_global",
            "ts:postgres_prod",
            "ts:postgres_prod_prefect",
            "ts:postgres_autodev_ts",
        ):
            arm = source.split(f"{route})", 1)[1].split(";;", 1)[0]
            self.assertIn("run_protected_postgres_uri", arm)
            self.assertNotIn('unrestricted', arm)

    def test_inventory_reports_configured_clients_and_clamp_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".mcp.json").write_text(json.dumps({
                "postgres_prod_prefect": {
                    "url": "http://127.0.0.1:8765/ts/postgres_prod_prefect/sse?access_mode=restricted"
                }
            }))
            gateway_log = root / "gateway.log"
            gateway_log.write_text(
                '2026-07-12 AUDIT {"event":"protected_access_mode_ceiling",'
                '"route":"ts/postgres_prod_prefect","requested":"unrestricted",'
                '"maximum":"restricted","policy":"clamp","outcome":"clamped"}\n'
            )
            result = subprocess.run([
                str(ROOT / "bin/mcp-protected-route-inventory"),
                "--root", str(root), "--gateway-log", str(gateway_log),
                "--root-owner", f"{root}=autodev-dashboard/F0017",
            ], capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["client_count"], 1)
            self.assertEqual(report["summary"]["unrestricted_requester_count"], 0)
            self.assertEqual(report["summary"]["clamp_event_count"], 1)
            self.assertEqual(report["clients"][0]["owner_ticket"],
                             "autodev-dashboard/F0017")

    def test_inventory_ignores_context_scratch_configs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".context").mkdir()
            value = '{"url":"http://127.0.0.1/ts/postgres_prod/sse?access_mode=unrestricted"}'
            (root / ".context/.mcp.json").write_text(value)
            (root / ".mcp.json").write_text(value.replace("unrestricted", "restricted"))
            result = subprocess.run([
                str(ROOT / "bin/mcp-protected-route-inventory"), "--root", str(root),
            ], capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["client_count"], 1)
            self.assertEqual(report["summary"]["unrestricted_requester_count"], 0)


if __name__ == "__main__":
    unittest.main()
