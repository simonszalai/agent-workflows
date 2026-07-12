from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GatewaySecurityTest(unittest.TestCase):
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
            ], capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["client_count"], 1)
            self.assertEqual(report["summary"]["unrestricted_requester_count"], 0)
            self.assertEqual(report["summary"]["clamp_event_count"], 1)
            self.assertEqual(report["clients"][0]["owner_ticket"], "ts-prefect/F0268")


if __name__ == "__main__":
    unittest.main()
