"""bin/import-render-env: create-only vault seeding from live Render env vars,
against fake op/curl. Values travel Render -> shell -> op stdin; the fakes
exit 91 if a value ever reaches argv."""

from __future__ import annotations

import unittest

from secrets_common import ROOT, SecretsSandbox, run

BIN = str(ROOT / "bin" / "import-render-env")

# Render env listing per service. Values start with "val-" so the fake op/curl
# argv leak guard catches any mishandling.
FAKE_CURL = r"""#!/usr/bin/env bash
set -uo pipefail
method="GET" url="" prev=""
for a in "$@"; do
  case "$a" in val-*|SENTINEL_*) echo "LEAK: secret value on curl argv" >&2; exit 91 ;; esac
  [[ "$prev" == "--request" ]] && method="$a"
  [[ "$prev" == "--url" ]] && url="$a"
  prev="$a"
done
cat >/dev/null
printf 'CURL %s %s\n' "$method" "$url" >> "$FAKE_LOG"
case "$method $url" in
  "GET https://api.render.com/v1/services/srv-beta/env-vars?limit=100")
    printf '[{"envVar":{"key":"BETA_ONE","value":"val-from-render-beta"}},{"envVar":{"key":"BETA_LIT","value":"plain-config"}}]' ;;
  "GET https://api.render.com/v1/services/srv-alpha/env-vars?limit=100")
    if [[ "${FAKE_RENDER_ALPHA_TWO_MISSING:-0}" == "1" ]]; then
      printf '[{"envVar":{"key":"ALPHA_ONE","value":"val-from-render-alpha1"}}]'
    else
      printf '[{"envVar":{"key":"ALPHA_ONE","value":"val-from-render-alpha1"}},{"envVar":{"key":"ALPHA_TWO","value":"val-from-render-alpha2"}}]'
    fi ;;
  *) printf '[]' ;;
esac
"""


class ImportRenderEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        curl = self.sb.fakebin / "curl"
        curl.write_text(FAKE_CURL, encoding="utf-8")
        curl.chmod(0o755)
        # The shared manifest routes ITEM (srv-alpha ALPHA_ONE, first), ITEM2
        # (srv-beta BETA_ONE) and OTHER (srv-alpha ALPHA_TWO) to render; ITEM
        # already exists in the vault.
        self.seed("op://TESTVAULT/ITEM/value", "val-existing")

    def seed(self, ref: str, value: str) -> None:
        vault, item, field = ref.removeprefix("op://").split("/")
        (self.sb.state / f"{vault}__{item}__{field}").write_text(value, encoding="utf-8")

    def stored(self, ref: str) -> str | None:
        vault, item, field = ref.removeprefix("op://").split("/")
        path = self.sb.state / f"{vault}__{item}__{field}"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def imp(self, *args: str, **extra: str):
        return run([BIN, "--repo", str(self.sb.repo), *args], self.sb.env(**extra))

    def test_dry_run_lists_missing_items_without_reading_values(self) -> None:
        proc = self.imp("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("would create op://TESTVAULT/ITEM2/value  <-  render[srv-beta] BETA_ONE", proc.stdout)
        self.assertIn("would create op://TESTVAULT/OTHER/value  <-  render[srv-alpha] ALPHA_TWO", proc.stdout)
        self.assertNotIn("ITEM/value", proc.stdout)
        log = self.sb.log_lines()
        self.assertFalse(any(l.startswith("CURL") for l in log))
        self.assertTrue(all("item list" in l for l in log if l.startswith("OP")), log)
        self.assertIsNone(self.stored("op://TESTVAULT/ITEM2/value"))

    def test_live_run_creates_only_missing_items_from_the_first_routed_service(self) -> None:
        proc = self.imp()
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.stored("op://TESTVAULT/ITEM2/value"), "val-from-render-beta")
        self.assertEqual(self.stored("op://TESTVAULT/OTHER/value"), "val-from-render-alpha2")
        self.assertEqual(self.stored("op://TESTVAULT/ITEM/value"), "val-existing")  # never touched
        self.assertIn("created op://TESTVAULT/ITEM2/value  <-  render[srv-beta] BETA_ONE", proc.stdout)
        combined = proc.stdout + proc.stderr + "\n".join(self.sb.log_lines())
        self.assertNotIn("val-from-render", combined)
        self.assertFalse(any("OP item edit" in l for l in self.sb.log_lines()))
        # One Render API key resolution, then env reads for the two source services.
        self.assertTrue(any("OP read --no-newline op://TESTVAULT/TEST_RENDER_API_KEY/value" in l
                            for l in self.sb.log_lines()))

    def test_missing_at_source_is_reported_and_exits_1_but_others_still_import(self) -> None:
        proc = self.imp(FAKE_RENDER_ALPHA_TWO_MISSING="1")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("MISSING at source too (render[srv-alpha] has no ALPHA_TWO)", proc.stderr)
        self.assertEqual(self.stored("op://TESTVAULT/ITEM2/value"), "val-from-render-beta")
        self.assertIsNone(self.stored("op://TESTVAULT/OTHER/value"))

    def test_second_run_finds_nothing_missing(self) -> None:
        self.assertEqual(self.imp().returncode, 0)
        self.sb.log_path.unlink()
        proc = self.imp()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("nothing missing", proc.stdout)
        self.assertFalse(any(l.startswith("CURL") for l in self.sb.log_lines()))

    def test_agent_shell_is_refused_before_any_call(self) -> None:
        proc = self.imp(CLAUDECODE="1")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("human terminal", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_unknown_flag_is_usage(self) -> None:
        self.assertEqual(self.imp("--bogus").returncode, 2)


if __name__ == "__main__":
    unittest.main()
