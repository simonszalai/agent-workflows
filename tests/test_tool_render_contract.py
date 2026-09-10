"""Regression contract for Render HTTP request metrics (B0431)."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_ROUTE = "/v1/metrics/http-requests"
RETIRED_ROUTE = "/v1/metrics/http-request-count"


class ToolRenderContractTests(unittest.TestCase):
    def test_http_request_metric_uses_supported_route(self) -> None:
        skill = (ROOT / "skills" / "tool-render" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(CURRENT_ROUTE, skill)
        self.assertNotIn(RETIRED_ROUTE, skill)


if __name__ == "__main__":
    unittest.main()
