from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXIES = ROOT / "mcp-proxies"


class McpProxyConfigurationTest(unittest.TestCase):
    def test_client_daemon_assets_are_removed(self) -> None:
        for relative in (
            "autodev-routes.env",
            "autodev-routes.json",
            "com.simon.mcp-proxies.plist",
            "context7.env",
            "start-cloud-proxies.sh",
            "start-proxies.sh",
            "verify-autodev-routes.mjs",
        ):
            self.assertFalse((PROXIES / relative).exists(), relative)

    def test_fixed_proxy_remains_only_for_the_hermes_service(self) -> None:
        install = (ROOT / "hermes/install.sh").read_text()
        runner = (ROOT / "hermes/bin/run-autodev-memory").read_text()
        self.assertIn("mcp-proxies/mcp-proxy.mjs", install)
        self.assertIn("mcp-proxy.mjs autodev-memory", runner)
        self.assertTrue((PROXIES / "mcp-proxy.mjs").is_file())
        self.assertTrue((PROXIES / "waf-encode.mjs").is_file())

    def test_session_hook_documents_inline_auth_not_retired_client_proxy(self) -> None:
        hook = (ROOT / "hooks/autodev-memory-session-start.sh").read_text()
        self.assertIn("Authentication is resolved inline", hook)
        self.assertNotIn("project-routed loopback proxy", hook)
        self.assertNotIn("AUTODEV_MEMORY_API_TOKEN", hook)


if __name__ == "__main__":
    unittest.main()
