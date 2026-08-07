"""bin/migrate-1p-grouping — mapping-driven 1Password item regrouping (slice 6).

Covers: credential-free plan mode, copy ordering (read -> upsert -> verify,
never delete), idempotent re-copy, verify gating, apply-refs rewrites +
refusal without verify state, and the print-only retire plan.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from secrets_common import AGENT_MARKERS

ROOT = Path(__file__).resolve().parents[1]
MIGRATE = ROOT / "bin" / "migrate-1p-grouping"

# Multi-field-capable fake op: items live as one JSON file per (vault, title)
# under $FAKE_OP_STATE/items. `item delete` hard-fails — this migration must
# never delete. Secret values on argv hard-fail (91) like the shared fakes.
FAKE_OP = r"""#!/usr/bin/env bash
set -uo pipefail
for a in "$@"; do
  case "$a" in val-*) echo "LEAK: secret value on op argv" >&2; exit 91 ;; esac
done
printf 'OP %s\n' "$*" >> "$FAKE_LOG"
items="${FAKE_OP_STATE:?}/items"
mkdir -p "$items"
slug() { printf '%s__%s' "$1" "$2" | tr ' /' '__'; }
file_by_id() { # id -> path or fail
  local f
  for f in "$items"/*.json; do
    [[ -e "$f" ]] || continue
    if [[ "$(jq -r '.id' "$f")" == "$1" ]]; then printf '%s' "$f"; return 0; fi
  done
  return 1
}
cmd="${1:-}"
case "$cmd" in
  read)
    ref=""
    for a in "$@"; do case "$a" in op://*) ref="$a" ;; esac; done
    rest="${ref#op://}"; v="${rest%%/*}"; rest="${rest#*/}"; i="${rest%%/*}"; f="${rest#*/}"
    path="$items/$(slug "$v" "$i").json"
    [[ -f "$path" ]] || { echo "fake op: no item $v/$i" >&2; exit 1; }
    val="$(jq -r --arg f "$f" '.fields[] | select(.label == $f) | .value' "$path")"
    [[ -n "$val" ]] || { echo "fake op: no field $f on $v/$i" >&2; exit 1; }
    printf '%s' "$val"
    ;;
  item)
    sub="${2:-}"
    vault=""; prev=""
    for a in "$@"; do [[ "$prev" == "--vault" ]] && vault="$a"; prev="$a"; done
    case "$sub" in
      list)
        printf '['
        first=1
        for f in "$items"/*.json; do
          [[ -e "$f" ]] || continue
          [[ "$(jq -r '.vault' "$f")" == "$vault" ]] || continue
          [[ $first -eq 1 ]] || printf ','
          jq -c '{id, title}' "$f" | tr -d '\n'
          first=0
        done
        printf ']\n'
        ;;
      create)
        json="$(cat)"
        v="$(jq -r '.vault.name' <<<"$json")"
        t="$(jq -r '.title' <<<"$json")"
        jq --arg id "id-$(slug "$v" "$t")" --arg v "$v" \
          '{id: $id, vault: $v, title, fields}' <<<"$json" \
          > "$items/$(slug "$v" "$t").json"
        printf '{"id":"id-%s"}\n' "$(slug "$v" "$t")"
        ;;
      get)
        path="$(file_by_id "${3:-}")" || { echo "fake op: item not found" >&2; exit 1; }
        jq '{id, title, fields}' "$path"
        ;;
      edit)
        path="$(file_by_id "${3:-}")" || { echo "fake op: item not found" >&2; exit 1; }
        json="$(cat)"
        id="$(jq -r '.id' "$path")"
        v="$(jq -r '.vault' "$path")"
        jq --arg id "$id" --arg v "$v" '{id: $id, vault: $v, title, fields}' <<<"$json" > "$path"
        printf '{"id":"%s"}\n' "$id"
        ;;
      delete)
        echo "fake op: item delete is FORBIDDEN in this migration" >&2
        exit 93
        ;;
      *) echo "fake op: unhandled item sub $sub" >&2; exit 1 ;;
    esac
    ;;
  *) echo "fake op: unhandled command $cmd" >&2; exit 1 ;;
esac
"""

MANIFEST = "\n".join(
    [
        "render\tsrv-x\tXAI_API_KEY\top://TV/XAI_API_KEY/value\tself",
        "render\tsrv-x\tDATABASE_URL\top://TV-sensitive/PROD_POSTGRES_URL_APPX/value\tself",
        "github\torg/repo\tNEW_TOKEN\top://TV/NOT_YET_MINTED/value\tself",
        "",
    ]
)

REGISTRY = {
    "schema_version": 1,
    "secrets": [{"id": "x", "ref": "op://TV/XAI_API_KEY/value"}],
}


class MigrateSandbox:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fakebin = self.root / "fakebin"
        self.state = self.root / "op-state"
        self.state_dir = self.root / "grouping-state"
        self.log_path = self.root / "fake.log"
        self.fakebin.mkdir()
        self.state.mkdir()
        self.state_dir.mkdir()

        op = self.fakebin / "op"
        op.write_text(FAKE_OP, encoding="utf-8")
        op.chmod(0o755)

        self.repo = self.root / "consumer-repo"
        (self.repo / "scripts" / "secrets").mkdir(parents=True)
        (self.repo / "scripts" / "secrets" / "manifest").write_text(
            MANIFEST, encoding="utf-8"
        )
        self.aw = self.root / "aw-repo"
        (self.aw / "config").mkdir(parents=True)
        (self.aw / "config" / "secret-rotation.json").write_text(
            json.dumps(REGISTRY, indent=2) + "\n", encoding="utf-8"
        )
        for repo in (self.repo, self.aw):
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

        self.config_path = self.root / "1p-grouping.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repos": [str(self.repo), str(self.aw)],
                    "mappings": [
                        {
                            "project": "tv",
                            "group": "xAI",
                            "old_ref": "op://TV/XAI_API_KEY/value",
                            "vault": "TV",
                            "new_item": "xAI",
                            "new_field": "api_key",
                        },
                        {
                            "project": "tv",
                            "group": "Postgres",
                            "old_ref": "op://TV-sensitive/PROD_POSTGRES_URL_APPX/value",
                            "vault": "TV-sensitive",
                            "new_item": "Postgres prod",
                            "new_field": "appx",
                        },
                        {
                            "project": "tv",
                            "group": "Minted later",
                            "old_ref": "op://TV/NOT_YET_MINTED/value",
                            "vault": "TV",
                            "new_item": "Minted later",
                            "new_field": "token",
                            "pending_source": True,
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def close(self) -> None:
        self._tmp.cleanup()

    def seed_item(self, vault: str, title: str, field: str, value: str) -> None:
        items = self.state / "items"
        items.mkdir(exist_ok=True)
        slug = f"{vault}__{title}".replace(" ", "_").replace("/", "_")
        items.joinpath(f"{slug}.json").write_text(
            json.dumps(
                {
                    "id": f"id-{slug}",
                    "vault": vault,
                    "title": title,
                    "fields": [{"label": field, "type": "CONCEALED", "value": value}],
                }
            ),
            encoding="utf-8",
        )

    def item(self, vault: str, title: str) -> dict:
        slug = f"{vault}__{title}".replace(" ", "_").replace("/", "_")
        return json.loads(
            (self.state / "items" / f"{slug}.json").read_text(encoding="utf-8")
        )

    def field_value(self, vault: str, title: str, field: str) -> str | None:
        try:
            item = self.item(vault, title)
        except FileNotFoundError:
            return None
        for f in item["fields"]:
            if f["label"] == field:
                return f["value"]
        return None

    def env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        for name in (*AGENT_MARKERS, "SECRETS_ALLOW_AGENT", "OP_BIN",
                     "SENSITIVE_ACCESS_REASON", "OP_ACCESS_REASON"):
            env.pop(name, None)
        env.update(
            {
                "PATH": f"{self.fakebin}:{env.get('PATH', '')}",
                "OP_BIN": str(self.fakebin / "op"),
                "FAKE_LOG": str(self.log_path),
                "FAKE_OP_STATE": str(self.state),
                "GROUPING_CONFIG": str(self.config_path),
                "GROUPING_STATE_DIR": str(self.state_dir),
            }
        )
        env.update(extra)
        return env

    def run(self, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            [str(MIGRATE), *args],
            env=env or self.env(),
            capture_output=True,
            text=True,
        )

    def log(self) -> str:
        if not self.log_path.exists():
            return ""
        return self.log_path.read_text(encoding="utf-8")


class MigrateGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = MigrateSandbox()
        self.addCleanup(self.sb.close)
        self.sb.seed_item("TV", "XAI_API_KEY", "value", "val-xai")
        self.sb.seed_item(
            "TV-sensitive", "PROD_POSTGRES_URL_APPX", "value", "val-pg-appx"
        )

    # --- plan ---------------------------------------------------------------
    def test_plan_is_credential_free(self) -> None:
        broken_op = self.sb.fakebin / "op"
        broken_op.write_text("#!/usr/bin/env bash\nexit 97\n", encoding="utf-8")
        res = self.sb.run("--plan")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.sb.log(), "")  # zero op invocations
        self.assertIn("op://TV/XAI_API_KEY/value -> op://TV/xAI/api_key", res.stdout)
        self.assertIn("[pending source]", res.stdout)
        self.assertIn("refs mapped: 3", res.stdout)

    def test_plan_rejects_sensitivity_mixing(self) -> None:
        cfg = json.loads(self.sb.config_path.read_text(encoding="utf-8"))
        cfg["mappings"][0]["new_item"] = "Postgres prod"  # regular TV vault
        self.sb.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        res = self.sb.run("--plan")
        self.assertEqual(res.returncode, 2)
        self.assertIn("sensitive AND a regular vault", res.stderr)

    # --- copy ---------------------------------------------------------------
    def test_copy_reads_upserts_verifies_never_deletes(self) -> None:
        res = self.sb.run("--copy", "--reason", "slice6 test")
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertEqual(self.sb.field_value("TV", "xAI", "api_key"), "val-xai")
        self.assertEqual(
            self.sb.field_value("TV-sensitive", "Postgres prod", "appx"),
            "val-pg-appx",
        )
        # pending mapping untouched
        self.assertIsNone(self.sb.field_value("TV", "Minted later", "token"))
        self.assertIn("skip (pending source)", res.stdout)
        # old items still intact, and no delete ever issued
        self.assertEqual(self.sb.field_value("TV", "XAI_API_KEY", "value"), "val-xai")
        self.assertNotIn("item delete", self.sb.log())
        # ordering per mapping: read the source before mutating the target
        lines = [l for l in self.sb.log().splitlines()
                 if "XAI_API_KEY" in l or "item create" in l]
        first_read = next(i for i, l in enumerate(lines) if "read" in l)
        first_write = next(i for i, l in enumerate(lines) if "item create" in l)
        self.assertLess(first_read, first_write)

    def test_copy_requires_reason(self) -> None:
        res = self.sb.run("--copy")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--reason", res.stderr)

    def test_copy_refused_from_agent_shell(self) -> None:
        env = self.sb.env(CLAUDECODE="1")
        res = self.sb.run("--copy", "--reason", "x", env=env)
        self.assertEqual(res.returncode, 3)

    def test_copy_is_idempotent(self) -> None:
        first = self.sb.run("--copy", "--reason", "slice6 test")
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.sb.item("TV", "xAI")
        marker = len(self.sb.log())
        second = self.sb.run("--copy", "--reason", "slice6 test")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.sb.item("TV", "xAI"), before)
        second_log = self.sb.log()[marker:]
        self.assertNotIn("item create", second_log)
        self.assertNotIn("item edit", second_log)
        self.assertNotIn("item delete", second_log)

    # --- verify + apply-refs -----------------------------------------------
    def test_apply_refs_refuses_without_verify(self) -> None:
        res = self.sb.run("--apply-refs")
        self.assertEqual(res.returncode, 3)
        self.assertIn("no --verify pass", res.stderr)
        manifest = (self.sb.repo / "scripts" / "secrets" / "manifest").read_text(
            encoding="utf-8"
        )
        self.assertIn("op://TV/XAI_API_KEY/value", manifest)  # untouched

    def test_verify_mismatch_blocks_apply_refs(self) -> None:
        self.sb.run("--copy", "--reason", "x")
        item = self.sb.item("TV", "xAI")
        item["fields"][0]["value"] = "val-tampered"
        slug = "TV__xAI"
        (self.sb.state / "items" / f"{slug}.json").write_text(
            json.dumps(item), encoding="utf-8"
        )
        res = self.sb.run("--verify")
        self.assertEqual(res.returncode, 1)
        self.assertIn("MISMATCH", res.stdout)
        self.assertEqual(self.sb.run("--apply-refs").returncode, 3)

    def test_verify_then_apply_refs_rewrites_working_trees(self) -> None:
        self.sb.run("--copy", "--reason", "x")
        verify = self.sb.run("--verify")
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("OK", verify.stdout)
        self.assertIn("PENDING", verify.stdout)

        res = self.sb.run("--apply-refs")
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        manifest = (self.sb.repo / "scripts" / "secrets" / "manifest").read_text(
            encoding="utf-8"
        )
        self.assertIn("XAI_API_KEY\top://TV/xAI/api_key", manifest)  # ENVNAME kept
        self.assertIn("op://TV-sensitive/Postgres prod/appx", manifest)
        # pending mappings are rewritten too (item minted later at the new ref)
        self.assertIn("op://TV/Minted later/token", manifest)
        self.assertNotIn("op://TV/XAI_API_KEY/value", manifest)
        registry = (self.sb.aw / "config" / "secret-rotation.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("op://TV/xAI/api_key", registry)
        self.assertIn(str(self.sb.repo), res.stdout)  # per-repo diff summary
        self.assertIn("scripts/secrets/manifest", res.stdout)

    def test_apply_refs_repo_granularity(self) -> None:
        self.sb.run("--copy", "--reason", "x")
        self.sb.run("--verify")
        res = self.sb.run("--apply-refs", "--repo", str(self.sb.aw))
        self.assertEqual(res.returncode, 0, res.stderr)
        manifest = (self.sb.repo / "scripts" / "secrets" / "manifest").read_text(
            encoding="utf-8"
        )
        self.assertIn("op://TV/XAI_API_KEY/value", manifest)  # other repo untouched
        registry = (self.sb.aw / "config" / "secret-rotation.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("op://TV/xAI/api_key", registry)

    def test_apply_refs_rejects_unlisted_repo(self) -> None:
        self.sb.run("--copy", "--reason", "x")
        self.sb.run("--verify")
        res = self.sb.run("--apply-refs", "--repo", str(self.sb.root))
        self.assertEqual(res.returncode, 2)

    # --- retire-plan ---------------------------------------------------------
    def test_retire_plan_lists_only_fully_migrated_items(self) -> None:
        res = self.sb.run("--retire-plan")
        self.assertEqual(res.returncode, 0)
        self.assertIn("no --verify pass", res.stdout)

        self.sb.run("--copy", "--reason", "x")
        self.sb.run("--verify")
        res = self.sb.run("--retire-plan")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("NOT safe", res.stdout)  # refs still in working trees

        self.sb.run("--apply-refs")
        res = self.sb.run("--retire-plan")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("safe: op://TV/XAI_API_KEY", res.stdout)
        self.assertIn("safe: op://TV-sensitive/PROD_POSTGRES_URL_APPX", res.stdout)
        self.assertIn("skip (pending source", res.stdout)
        self.assertNotIn("item delete", self.sb.log())


if __name__ == "__main__":
    unittest.main()
