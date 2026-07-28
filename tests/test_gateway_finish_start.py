from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINISH_START = ROOT / "mcp-gateway" / "finish-start.zsh"
START_GATEWAY = ROOT / "mcp-gateway" / "start-gateway.sh"


class GatewayFinishStartTests(unittest.TestCase):
    def test_startup_clears_inherited_hermes_credentials_before_op_run(self) -> None:
        source = START_GATEWAY.read_text(encoding="utf-8")
        clear = "unset HERMES_AUTODEV_MEMORY_TOKEN HERMES_GATEWAY_TOKEN"
        self.assertIn(clear, source)
        self.assertLess(source.index(clear), source.index('"$OP_BIN" run'))

    def test_derives_prod_urls_scrubs_canonical_and_forwards_validation_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            capture = directory / "capture.json"
            fake_node = directory / "node"
            fake_node.write_text(
                """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
Path(os.environ["CAPTURE"]).write_text(json.dumps({
    "argv": sys.argv[1:],
    "prod": os.environ.get("TS_POSTGRES_PROD_URL"),
    "prefect": os.environ.get("TS_POSTGRES_PROD_PREFECT_URL"),
    "canonical_present": "TS_PROD_POSTGRES_URL" in os.environ,
}))
""",
                encoding="utf-8",
            )
            fake_node.chmod(0o700)
            env = {
                **os.environ,
                "NODE_BIN": str(fake_node),
                "CAPTURE": str(capture),
                "TS_PROD_POSTGRES_URL": (
                    "\npostgresql://user:pass@db.example/app?sslmode=require\t"
                ),
            }
            result = subprocess.run(
                [str(FINISH_START), "--validate"],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            observed = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(
                observed["argv"][-1:],
                ["--validate"],
            )
            self.assertTrue(observed["argv"][0].endswith("/mcp-gateway/gateway.mjs"))
            self.assertEqual(
                observed["prod"],
                "postgresql://user:pass@db.example/app?sslmode=require",
            )
            self.assertEqual(
                observed["prefect"],
                "postgresql://user:pass@db.example/prefect?sslmode=require",
            )
            self.assertFalse(observed["canonical_present"])

            rejected = subprocess.run(
                [str(FINISH_START), "--unknown"],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )
            self.assertEqual(rejected.returncode, 64)
            self.assertIn("accepts only --validate", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
