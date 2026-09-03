"""Unit coverage for the shared secrets engine libraries (secrets/lib/)."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import yaml

from secrets_common import ROOT, SHELL_FILES, SecretsSandbox, run

LIB = ROOT / "secrets" / "lib"


def bash_lib(snippet: str, env: dict[str, str], *, stdin: str | None = None,
             config: str | None = None) -> subprocess.CompletedProcess[str]:
    if config is not None:
        env = dict(env)
        env["_SECRETS_CONFIG"] = config
    script = f'source "{LIB}/config.sh"; source "{LIB}/read.sh"; source "{LIB}/derive.sh"; {snippet}'
    return run(["bash", "-c", script], env, stdin=stdin)


class ShellSyntaxTest(unittest.TestCase):
    def test_every_engine_shell_file_parses_under_bash_n(self) -> None:
        for rel in SHELL_FILES:
            with self.subTest(rel):
                proc = subprocess.run(
                    ["bash", "-n", str(ROOT / rel)], capture_output=True, text=True
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)


class ManifestValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.config = self.sb.repo

    def validate(self, content: str) -> subprocess.CompletedProcess[str]:
        self.sb.write_manifest(content)
        return bash_lib("config_validate", self.sb.env(), config=str(self.config))

    def test_committed_style_config_validates_cleanly(self) -> None:
        proc = bash_lib("config_validate", self.sb.env(), config=str(self.config))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_wrong_field_count_rejects_the_whole_manifest(self) -> None:
        proc = self.validate("github\ta/b\tNAME\top://V/I/value\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing/empty", proc.stderr)

    def test_empty_field_rejects(self) -> None:
        proc = self.validate("github\t\tNAME\top://V/I/value\tself\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing/empty dest", proc.stderr)

    def test_unknown_kind_rejects(self) -> None:
        proc = self.validate("s3\ta/b\tNAME\top://V/I/value\tself\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown kind", proc.stderr)

    def test_hermes_kind_validates_with_abs_dest_and_ssh(self) -> None:
        self.sb.write_manifest(
            "hermes\t/etc/hermes-mcp/x.token\tNAME\top://V/I/value\tself\n",
            hermes={"ssh": "hermes"},
        )
        proc = bash_lib("config_validate", self.sb.env(), config=str(self.config))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_hermes_relative_dest_rejects(self) -> None:
        self.sb.write_manifest(
            "hermes\tx.token\tNAME\top://V/I/value\tself\n",
            hermes={"ssh": "hermes"},
        )
        proc = bash_lib("config_validate", self.sb.env(), config=str(self.config))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("absolute file path", proc.stderr)

    def test_hermes_route_without_ssh_rejects(self) -> None:
        proc = self.validate("hermes\t/etc/hermes-mcp/x.token\tNAME\top://V/I/value\tself\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("hermes.ssh", proc.stderr)

    def test_unknown_transform_rejects(self) -> None:
        proc = self.validate("github\ta/b\tNAME\top://V/I/value\trot13\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown transform", proc.stderr)

    def test_ref_missing_field_segment_rejects(self) -> None:
        proc = self.validate("github\ta/b\tNAME\top://V/I\tself\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("REF needs vault/item/field", proc.stderr)

    def test_arbitrary_field_names_are_accepted_for_product_grouped_items(self) -> None:
        proc = self.validate("render\tsrv-x\tDATABASE_URL\top://V/Postgres prod/app\tself\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_duplicate_kind_dest_envname_rejects(self) -> None:
        proc = self.validate(
            "github\ta/b\tNAME\top://V/I/value\tself\n"
            "github\ta/b\tNAME\top://V/J/value\tself\n"
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate route", proc.stderr)

    # --- sync_repos (cross-project fan-out) -----------------------------------

    def _with_sync_repos(self, value, sibling: dict | None = None) -> subprocess.CompletedProcess[str]:
        """Write a one-route/one-rotation config declaring sync_repos=value, plus
        an optional sibling project config at <root>/other/secrets.yaml."""
        ref = "op://V/I/value"
        if sibling is not None:
            other = self.sb.root / "other"
            other.mkdir(exist_ok=True)
            (other / "secrets.yaml").write_text(
                yaml.safe_dump(sibling, sort_keys=False), encoding="utf-8"
            )
        self.sb.write_manifest(
            f"render\tsrv-x\tE\t{ref}\tself\n",
            rotation={"e1": {
                "ref": ref, "provider": "self_minted", "mode": "SELF_MINTED",
                "owner_repo": "repo", "sync_repos": value,
            }},
        )
        return bash_lib("config_validate", self.sb.env(), config=str(self.config))

    def _sibling(self, project: str, ref: str) -> dict:
        return {
            "project": project, "repos": ["other"], "health": {}, "routes": [
                {"repo": "other", "kind": "github", "dest": "o/o",
                 "env": "E", "ref": ref, "transform": "self"}
            ],
        }

    def test_sync_repos_accepts_a_sibling_project_routing_the_same_ref(self) -> None:
        proc = self._with_sync_repos(
            ["../other"], self._sibling("otherproj", "op://V/I/value")
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_sync_repos_rejects_a_nonexistent_repo(self) -> None:
        proc = self._with_sync_repos(["../nope"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("does not exist", proc.stderr)

    def test_sync_repos_rejects_the_same_project(self) -> None:
        proc = self._with_sync_repos(
            ["../other"], self._sibling("testproj", "op://V/I/value")
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("is the same project", proc.stderr)

    def test_sync_repos_rejects_a_sibling_that_does_not_route_the_ref(self) -> None:
        proc = self._with_sync_repos(
            ["../other"], self._sibling("otherproj", "op://V/UNRELATED/value")
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("routes none of", proc.stderr)

    def test_sync_repos_rejects_a_bare_string(self) -> None:
        proc = self._with_sync_repos("../other", self._sibling("otherproj", "op://V/I/value"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must be a list of non-empty strings", proc.stderr)

    # --- cross-vault service-account routing ----------------------------------

    def _vault_owner_fixture(self) -> tuple[str, str]:
        """A project registry where testproj owns TESTVAULT and otherproj owns
        OTHERVAULT, plus a fake op that reports whether a token was PINNED by
        read.sh rather than left for the shim's owner routing."""
        registry = self.sb.root / "vault-owners.json"
        registry.write_text(
            json.dumps({
                "schema_version": 1,
                "projects": {
                    "testproj": {"service_account": {
                        "keychain_item": "op-testproj-token", "vaults": ["TESTVAULT"]}},
                    "otherproj": {"service_account": {
                        "keychain_item": "op-otherproj-token", "vaults": ["OTHERVAULT"]}},
                },
            }),
            encoding="utf-8",
        )
        probe = self.sb.root / "op-probe"
        probe.write_text(
            '#!/usr/bin/env bash\n'
            'if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then echo PINNED; else echo UNPINNED; fi\n',
            encoding="utf-8",
        )
        probe.chmod(0o755)
        return str(registry), str(probe)

    def _read_ref(self, ref: str) -> subprocess.CompletedProcess[str]:
        registry, probe = self._vault_owner_fixture()
        env = self.sb.env(
            PROJECT_TOOLS_CONFIG=registry,
            OP_BIN=probe,
            SECRETS_SA_KEYCHAIN_ITEM="op-testproj-token",
            SECRETS_SA_TOKEN_ENV="TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
        )
        return bash_lib(f'op_read_ref "{ref}"', env, config=str(self.config))

    def test_own_vault_still_uses_the_running_projects_pinned_token(self) -> None:
        proc = self._read_ref("op://TESTVAULT/ITEM/value")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "PINNED")

    def test_another_projects_vault_is_left_for_owner_routing(self) -> None:
        """Pinning the running project's token here is what produced
        `could not read secret: "TS" isn't a vault in this account` and the
        RESOLVE FAILED rows on every autodev rotation of the TS-owned API
        token."""
        proc = self._read_ref("op://OTHERVAULT/ITEM/value")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "UNPINNED")

    def test_unregistered_vault_keeps_the_pinned_token_path(self) -> None:
        """An unregistered vault is not evidence of another owner, so behavior
        is unchanged (the shim still fails closed on its own terms)."""
        proc = self._read_ref("op://UNKNOWNVAULT/ITEM/value")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "PINNED")

    def test_missing_manifest_file_returns_2(self) -> None:
        proc = bash_lib(
            "config_validate", self.sb.env(), config=str(self.sb.root / "nope")
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no secrets config", proc.stderr)

    def test_config_rows_ref_filter_is_exact_equality_not_substring(self) -> None:
        self.sb.write_manifest(
            "render\tsrv-x\tA\top://V/ITEM/value\tself\n"
            "render\tsrv-x\tB\top://V/ITEM2/value\tself\n"
        )
        proc = bash_lib(
            'config_rows render "" "op://V/ITEM/value"',
            self.sb.env(),
            config=str(self.config),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("\tA\t", proc.stdout)
        self.assertNotIn("ITEM2", proc.stdout)

    def test_config_rows_prefix_filter_matches_item_prefix_never_substring(self) -> None:
        self.sb.write_manifest(
            "render\tsrv-x\tA\top://V/ITEM/value\tself\n"
            "render\tsrv-x\tB\top://V/ITEM2/value\tself\n"
            "render\tsrv-x\tC\top://V/ITEM/other\tself\n"
        )
        proc = bash_lib(
            'config_rows render "" "" "op://V/ITEM/"',
            self.sb.env(),
            config=str(self.config),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        names = sorted(l.split("\t")[2] for l in proc.stdout.splitlines())
        self.assertEqual(names, ["A", "C"])


class ProviderCommonTest(unittest.TestCase):
    def test_bearer_curl_non_2xx_reports_a_truncated_first_line_only(self) -> None:
        sb = SecretsSandbox()
        self.addCleanup(sb.close)
        script = (
            f'source "{LIB}/read.sh"; source "{LIB}/vault.sh"; source "{LIB}/provider-common.sh"; '
            'curl() { cat >/dev/null; printf "%s\\nSECOND-LINE-%s\\n500" "$(head -c 600 /dev/zero | tr "\\0" x)" "$(head -c 300 /dev/zero | tr "\\0" y)"; }; '
            'BEARER_KEY=k; bearer_curl POST https://api.test/v1/x <<< "{}" >/dev/null; echo "rc=$?"'
        )
        proc = run(["bash", "-c", script], sb.env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("rc=22", proc.stdout)
        err = proc.stderr.strip().splitlines()
        self.assertEqual(len(err), 1, proc.stderr)
        self.assertIn("returned HTTP 500: " + "x" * 200, err[0])
        self.assertNotIn("x" * 201, err[0])
        self.assertNotIn("SECOND-LINE", proc.stderr)


class VaultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        (self.sb.state / "TESTVAULT__ITEM__value").write_text("old-1", encoding="utf-8")
        (self.sb.state / "TESTVAULT__ITEM__other").write_text("old-2", encoding="utf-8")
        self.lockdir = self.sb.root / "locks"
        self.lockdir.mkdir()

    def vault(self, snippet: str, **extra: str) -> subprocess.CompletedProcess[str]:
        env = self.sb.env(VAULT_LOCK_DIR=str(self.lockdir), **extra)
        script = f'source "{LIB}/read.sh"; source "{LIB}/vault.sh"; {snippet}'
        return run(["bash", "-c", script], env)

    def op_lists(self) -> int:
        return len([l for l in self.sb.log_lines() if l.startswith("OP item list")])

    def test_replace_value_lists_the_vault_once(self) -> None:
        proc = self.vault('VAULT_VALUE=new-1 vault_write_value op://TESTVAULT/ITEM/value')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.sb.state / "TESTVAULT__ITEM__value").read_text(), "new-1")
        self.assertEqual(self.op_lists(), 1)

    def test_create_relists_after_creating(self) -> None:
        proc = self.vault('VAULT_VALUE=fresh vault_write_value op://TESTVAULT/NEWITEM/value')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.sb.state / "TESTVAULT__NEWITEM__value").read_text(), "fresh")
        self.assertEqual(self.op_lists(), 2)  # before (absent) + proof after create

    def test_stale_lock_from_a_dead_pid_is_reclaimed(self) -> None:
        # Pre-create the lock dir with a pid that is certainly gone.
        proc = self.vault(
            'key="$(printf %s TESTVAULT | shasum -a 256 | cut -c1-16)"; '
            'mkdir "$VAULT_LOCK_DIR/$key.lock"; printf 999999 > "$VAULT_LOCK_DIR/$key.lock/pid"; '
            'VAULT_VALUE=new-1 vault_replace_value op://TESTVAULT/ITEM/value',
            VAULT_LOCK_TIMEOUT_SECONDS="3",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("reclaiming stale lock", proc.stderr)
        self.assertEqual((self.sb.state / "TESTVAULT__ITEM__value").read_text(), "new-1")
        self.assertEqual(list(self.lockdir.iterdir()), [])  # released after use

    def test_stale_lock_reclaim_under_contention_admits_one_holder_at_a_time(self) -> None:
        # Four waiters find the same stale lock at once. Reclaim must be
        # atomic: every waiter eventually holds the lock, but their hold
        # intervals never overlap (the old rm-pid + rmdir reclaim let a
        # waiter delete the pid of a lock another waiter had just re-taken).
        spans = self.sb.root / "spans"
        spans.mkdir()
        proc = self.vault(
            'key="$(printf %s TESTVAULT | shasum -a 256 | cut -c1-16)"; '
            'mkdir "$VAULT_LOCK_DIR/$key.lock"; printf 999999 > "$VAULT_LOCK_DIR/$key.lock/pid"; '
            'worker() { local d; d="$(vault_item_lock_acquire TESTVAULT)" || exit 1; '
            '  printf "%s " "$(perl -MTime::HiRes=time -e "print time")" > "$SPANS/$1"; sleep 0.3; '
            '  printf "%s" "$(perl -MTime::HiRes=time -e "print time")" >> "$SPANS/$1"; '
            '  vault_item_lock_release "$d"; }; '
            'for i in 1 2 3 4; do worker "$i" & done; wait',
            VAULT_LOCK_TIMEOUT_SECONDS="10", SPANS=str(spans),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr.count("reclaiming stale lock"), 1, proc.stderr)
        intervals = sorted(tuple(float(x) for x in (spans / n).read_text().split())
                           for n in ("1", "2", "3", "4"))
        self.assertEqual(len(intervals), 4)
        for (_, end_a), (start_b, _) in zip(intervals, intervals[1:]):
            self.assertLessEqual(end_a, start_b, intervals)
        self.assertEqual(list(self.lockdir.iterdir()), [])

    def test_live_lock_holder_is_waited_for_not_reclaimed(self) -> None:
        proc = self.vault(
            'key="$(printf %s TESTVAULT | shasum -a 256 | cut -c1-16)"; '
            'mkdir "$VAULT_LOCK_DIR/$key.lock"; printf %s "$$" > "$VAULT_LOCK_DIR/$key.lock/pid"; '
            'VAULT_VALUE=new-1 vault_replace_value op://TESTVAULT/ITEM/value',
            VAULT_LOCK_TIMEOUT_SECONDS="2",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("timed out waiting for the vault item lock", proc.stderr)
        self.assertEqual((self.sb.state / "TESTVAULT__ITEM__value").read_text(), "old-1")

    def test_replace_fields_edits_both_fields_in_one_item_edit(self) -> None:
        proc = self.vault(
            'A=new-1 B=new-2 vault_replace_fields op://TESTVAULT/ITEM/value=A op://TESTVAULT/ITEM/other=B'
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.sb.state / "TESTVAULT__ITEM__value").read_text(), "new-1")
        self.assertEqual((self.sb.state / "TESTVAULT__ITEM__other").read_text(), "new-2")
        self.assertEqual(len([l for l in self.sb.log_lines() if l.startswith("OP item edit")]), 1)
        self.assertIn("updated 2 fields", proc.stdout)
        self.assertNotIn("new-", proc.stdout + proc.stderr + "\n".join(self.sb.log_lines()))

    def test_replace_fields_refuses_mixed_items_and_empty_values(self) -> None:
        proc = self.vault('A=x B=y vault_replace_fields op://TESTVAULT/ITEM/value=A op://TESTVAULT/OTHER/value=B')
        self.assertEqual(proc.returncode, 2)
        self.assertIn("one item", proc.stderr)
        proc = self.vault('A=x vault_replace_fields op://TESTVAULT/ITEM/value=A op://TESTVAULT/ITEM/other=UNSET_VAR')
        self.assertEqual(proc.returncode, 1)
        self.assertIn("empty value", proc.stderr)
        self.assertEqual((self.sb.state / "TESTVAULT__ITEM__value").read_text(), "old-1")

    def test_replace_fields_upserts_a_missing_field(self) -> None:
        proc = self.vault('A=x vault_replace_fields op://TESTVAULT/ITEM/nope=A')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.sb.state / "TESTVAULT__ITEM__nope").read_text(), "x")
        self.assertIn("updated 1 fields", proc.stdout)


class RetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def retry(self, snippet: str) -> subprocess.CompletedProcess[str]:
        script = f'source "{LIB}/read.sh"; RETRY_BASE_SECONDS=0; {snippet}'
        return run(["bash", "-c", script], self.sb.env())

    def test_transient_rc_is_retried_until_success(self) -> None:
        proc = self.retry(
            'n=0; flaky() { n=$((n+1)); echo "$n" >> "$FAKE_OP_STATE/calls"; [[ -f "$FAKE_OP_STATE/calls" && $(wc -l < "$FAKE_OP_STATE/calls") -ge 3 ]] || return 56; cat; }; '
            'RETRY_STDIN=body retry_transient flaky'
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "body")  # stdin re-fed on the winning attempt
        self.assertEqual((self.sb.state / "calls").read_text().count("\n"), 3)

    def test_hard_failure_is_not_retried(self) -> None:
        proc = self.retry('hard() { echo "$1" >> "$FAKE_OP_STATE/calls"; echo "permission denied" >&2; return 1; }; retry_transient hard x')
        self.assertEqual(proc.returncode, 1)
        self.assertEqual((self.sb.state / "calls").read_text(), "x\n")
        self.assertIn("permission denied", proc.stderr)

    def test_transient_stderr_pattern_is_bounded_by_retry_max(self) -> None:
        proc = self.retry('RETRY_MAX=2; g() { echo x >> "$FAKE_OP_STATE/calls"; echo "HTTP 503 Service Unavailable" >&2; return 1; }; retry_transient g')
        self.assertEqual(proc.returncode, 1)
        self.assertEqual((self.sb.state / "calls").read_text().count("x"), 3)


class SaTokenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def test_keychain_account_defaults_to_user_and_honours_override(self) -> None:
        proc = bash_lib('sa_token_account', self.sb.env(USER="alice"))
        self.assertEqual(proc.stdout, "alice")
        proc = bash_lib('sa_token_account', self.sb.env(SECRETS_SA_KEYCHAIN_ACCOUNT="svc"))
        self.assertEqual(proc.stdout, "svc")

    def test_keychain_is_read_once_per_process(self) -> None:
        # fake `security` exits 1 (no token): the process-level cache must still
        # only consult it once when the caller preloads in the main shell.
        env = self.sb.env(sa_token=False, SECRETS_SA_TOKEN_ENV="TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
                          SECRETS_SA_KEYCHAIN_ITEM="op-testproj-token", USER="bob")
        proc = bash_lib('sa_token >/dev/null; echo rc=$?; sa_token >/dev/null; echo rc=$?', env)
        self.assertEqual(proc.stdout.count("rc=3"), 2)
        sec = [l for l in self.sb.log_lines() if l.startswith("SECURITY")]
        self.assertEqual(len(sec), 2)  # a miss is not cached
        self.assertIn("-a bob", sec[0])
        # a hit IS cached: subsequent reads (even from subshells) skip the Keychain
        sec_bin = self.sb.fakebin / "security"
        sec_bin.write_text('#!/usr/bin/env bash\nprintf "SECURITY %s\\n" "$*" >> "$FAKE_LOG"; printf tok\n', encoding="utf-8")
        self.sb.log_path.unlink()
        proc = bash_lib('sa_token >/dev/null; a="$(sa_token)"; b="$(sa_token)"; echo "$a$b"', env)
        self.assertEqual(proc.stdout.strip(), "toktok")
        self.assertEqual(len([l for l in self.sb.log_lines() if l.startswith("SECURITY")]), 1)


class ConfigSchemaValidationTest(unittest.TestCase):
    """Strict-schema rules: unknown keys, duplicates, provider/mode/owner/repos
    consistency, per-provider config, generate, prefect dests. Every failure is
    exit 2 with a `<path>: <where>: <why>` line; the valid baseline passes."""

    REF = "op://V/I/value"
    REF2 = "op://V/J/value"

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def doc(self, **over) -> dict:
        d = {
            "project": "testproj",
            "repos": ["repo"],
            "health": {},
            "rotation": {"e1": {"ref": self.REF, "provider": "self_minted",
                                "mode": "SELF_MINTED", "owner_repo": "repo"}},
            "routes": [
                {"repo": "repo", "kind": "render", "dest": "srv-x", "env": "A",
                 "ref": self.REF, "transform": "self"},
                {"repo": "repo", "kind": "render", "dest": "srv-y", "env": "B",
                 "ref": self.REF2, "transform": "self"},
            ],
        }
        d.update(over)
        return d

    def validate_doc(self, doc: dict | None = None, raw: str | None = None):
        text = raw if raw is not None else yaml.safe_dump(doc, sort_keys=False)
        (self.sb.repo / "secrets.yaml").write_text(text, encoding="utf-8")
        return bash_lib("config_validate", self.sb.env(), config=str(self.sb.repo))

    def assert_rejects(self, doc=None, *, raw=None, msg: str):
        proc = self.validate_doc(doc, raw=raw)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn(msg, proc.stderr)
        self.assertIn(str(self.sb.repo / "secrets.yaml"), proc.stderr)

    def entry(self, **over) -> dict:
        e = {"ref": self.REF, "provider": "self_minted", "mode": "SELF_MINTED", "owner_repo": "repo"}
        e.update(over)
        return e

    def test_baseline_document_validates(self) -> None:
        proc = self.validate_doc(self.doc())
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_unknown_top_level_key_rejects(self) -> None:
        self.assert_rejects(self.doc(extra=1), msg="unknown top-level key 'extra'")

    def test_unknown_entry_key_rejects_including_automated(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(automated=True)}),
                            msg="rotation 'e1': unknown key 'automated'")

    def test_unknown_route_key_rejects(self) -> None:
        d = self.doc()
        d["routes"][0]["note"] = "x"
        self.assert_rejects(d, msg="route 1: unknown key 'note'")

    def test_duplicate_yaml_keys_reject(self) -> None:
        raw = (
            "project: testproj\nrepos: [repo]\nhealth: {}\n"
            "rotation:\n"
            "  e1: {ref: op://V/I/value, provider: self_minted, mode: SELF_MINTED, owner_repo: repo}\n"
            "  e1: {ref: op://V/J/value, provider: self_minted, mode: SELF_MINTED, owner_repo: repo}\n"
            "routes:\n"
            "  - {repo: repo, kind: render, dest: srv-x, env: A, ref: op://V/I/value, transform: self}\n"
            "  - {repo: repo, kind: render, dest: srv-y, env: B, ref: op://V/J/value, transform: self}\n"
        )
        self.assert_rejects(raw=raw, msg="duplicate key 'e1'")

    def test_two_entries_with_the_same_ref_reject(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(), "e2": self.entry()}),
                            msg="rotation 'e2': ref op://V/I/value is already rotated by 'e1'")

    def test_provider_without_handler_rejects(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(provider="xai", mode="MANUAL")}),
                            msg="rotation 'e1': provider 'xai' has no handler")

    def test_bad_mode_rejects(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(mode="ROLLING")}),
                            msg="mode must be one of DUAL_KEY, IN_PLACE, MANUAL, SELF_MINTED, got 'ROLLING'")

    def test_missing_required_entry_keys_reject(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": {"ref": self.REF}}),
                            msg="rotation 'e1': missing provider, mode, owner_repo")

    def test_owner_repo_not_in_repos_rejects(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(owner_repo="elsewhere")}),
                            msg="owner_repo 'elsewhere' is not listed in top-level 'repos'")

    def test_repos_must_list_every_routed_repo(self) -> None:
        d = self.doc()
        d["routes"][1]["repo"] = "other"
        self.assert_rejects(d, msg="route 2: repo 'other' is not listed in top-level 'repos'")
        self.assert_rejects(self.doc(repos=[]), msg="'repos' must be a non-empty list")

    def test_prefect_dest_must_be_a_tier(self) -> None:
        d = self.doc()
        d["routes"].append({"repo": "repo", "kind": "prefect", "dest": "qa", "env": "C",
                            "ref": self.REF, "transform": "self"})
        self.assert_rejects(d, msg="route 3: prefect dest must be staging or prod, got 'qa'")

    def test_sync_refs_must_be_routed_op_refs(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(sync_refs=["op://V/NOPE/value"])}),
                            msg="sync_refs entry op://V/NOPE/value has no route")
        self.assert_rejects(self.doc(rotation={"e1": self.entry(sync_refs=["literal:x"])}),
                            msg="is not an op://vault/item/field ref")

    def test_exclude_dests_must_name_a_dest_routing_the_entry(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(exclude_dests=["srv-y"])}),
                            msg="exclude_dests names 'srv-y', which routes none of the entry's refs")
        ok = self.validate_doc(self.doc(rotation={"e1": self.entry(exclude_dests=["srv-x"])}))
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_generate_is_validated(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(generate={"bytes": "32"})}),
                            msg="generate.bytes must be an integer 1..4096, got '32'")
        self.assert_rejects(self.doc(rotation={"e1": self.entry(generate={"format": "uuid"})}),
                            msg="generate.format must be hex or base64")
        self.assert_rejects(self.doc(rotation={"e1": self.entry(generate={"length": 3})}),
                            msg="generate: unknown key 'length'")

    def test_provider_config_required_keys_are_sync_only_not_errors(self) -> None:
        for provider, cfg in (("resend", {}), ("openai", {"project_id": "p"}),
                              ("aws_iam", {"iam_user": "u"})):
            with self.subTest(provider=provider):
                proc = self.validate_doc(self.doc(rotation={"e1": self.entry(
                    provider=provider, mode="DUAL_KEY", config=cfg or None)}))
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_provider_config_unknown_key_rejects(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(
            provider="resend", mode="DUAL_KEY", config={"key_name": "k", "api_key": "x"})}),
            msg="config: unknown key 'api_key' for provider resend")
        self.assert_rejects(self.doc(rotation={"e1": self.entry(config={"x": 1})}),
                            msg="provider self_minted takes no config")

    def test_aws_secret_ref_must_be_routed_and_in_sync_refs(self) -> None:
        self.assert_rejects(self.doc(rotation={"e1": self.entry(
            provider="aws_iam", mode="DUAL_KEY",
            config={"iam_user": "u", "secret_ref": "op://V/NOPE/value", "profile": "p"})}),
            msg="config.secret_ref op://V/NOPE/value has no route")
        self.assert_rejects(self.doc(rotation={"e1": self.entry(
            provider="aws_iam", mode="DUAL_KEY", sync_refs=[self.REF],
            config={"iam_user": "u", "secret_ref": self.REF2, "profile": "p"})}),
            msg="aws_iam sync_refs must include config.secret_ref")

    def test_hermes_section_shape(self) -> None:
        self.assert_rejects(self.doc(hermes={"ssh": "h", "port": 22}),
                            msg="'hermes' must be exactly {ssh:")

    def test_pointer_resolves_and_config_path_prints_target(self) -> None:
        primary = self.sb.root / "primary"
        primary.mkdir()
        (primary / "secrets.yaml").write_text(yaml.safe_dump(self.doc(), sort_keys=False), encoding="utf-8")
        (self.sb.repo / "secrets.yaml").write_text("extends: ../primary/secrets.yaml\n", encoding="utf-8")
        proc = bash_lib("config_path", self.sb.env(), config=str(self.sb.repo))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(primary / "secrets.yaml"))
        (self.sb.repo / "secrets.yaml").write_text("extends: ../primary/secrets.yaml\nproject: x\n", encoding="utf-8")
        proc = bash_lib("config_path", self.sb.env(), config=str(self.sb.repo))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("a pointer must contain only", proc.stderr)

    def test_registry_file_is_content_addressed_and_private(self) -> None:
        import os
        regdir = self.sb.root / "registry"
        (self.sb.repo / "secrets.yaml").write_text(yaml.safe_dump(self.doc(), sort_keys=False), encoding="utf-8")
        env = self.sb.env(SECRETS_REGISTRY_DIR=str(regdir))
        first = bash_lib("config_registry", env, config=str(self.sb.repo))
        second = bash_lib("config_registry", env, config=str(self.sb.repo))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        path = first.stdout.strip()
        self.assertTrue(path.startswith(str(regdir)))
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.assertEqual(len(list(regdir.glob("*.json"))), 1)
        reg = json.loads(open(path).read())
        self.assertEqual(reg["secrets"][0]["id"], "e1")
        self.assertEqual(reg["secrets"][0]["consumers"], [{"repo": "repo", "dest": "srv-x", "env": "A"}])


class DeriveTransformTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def derive(self, transform: str, value: str) -> subprocess.CompletedProcess[str]:
        return bash_lib(f"apply_transform '{transform}'", self.sb.env(), stdin=value)

    URL = "postgresql://user:p%40ss@host.frankfurt-postgres.render.com:5432/maindb?sslmode=require"

    def test_self_passes_through(self) -> None:
        proc = self.derive("self", "plain-value\n")
        self.assertEqual((proc.returncode, proc.stdout), (0, "plain-value"))

    def test_no_query_strips_options(self) -> None:
        proc = self.derive("no-query", self.URL)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout,
            "postgresql://user:p%40ss@host.frankfurt-postgres.render.com:5432/maindb",
        )

    def test_conn_id_accepts_kinde_connection_ids_only(self) -> None:
        ok = self.derive("conn-id", "conn_abc123")
        self.assertEqual((ok.returncode, ok.stdout), (0, "conn_abc123"))
        bad = self.derive("conn-id", "not-a-conn-id")
        self.assertEqual(bad.returncode, 3)

    def test_db_swaps_database_and_keeps_query(self) -> None:
        proc = self.derive("db=mem_ts", self.URL)
        self.assertEqual(
            proc.stdout,
            "postgresql://user:p%40ss@host.frankfurt-postgres.render.com:5432/mem_ts?sslmode=require",
        )

    def test_pgbouncer_forces_plain_scheme_and_drops_query(self) -> None:
        proc = self.derive("pgbouncer=bouncer:6432/mydb", self.URL)
        self.assertEqual(proc.stdout, "postgresql://user:p%40ss@bouncer:6432/mydb")

    def test_asyncpg_internal_uses_short_host(self) -> None:
        proc = self.derive("asyncpg-internal=prefect", self.URL)
        self.assertEqual(proc.stdout, "postgresql+asyncpg://user:p%40ss@host:5432/prefect")

    def test_asyncpg_external_keeps_full_host(self) -> None:
        proc = self.derive("asyncpg-external=prefect", self.URL)
        self.assertEqual(
            proc.stdout,
            "postgresql+asyncpg://user:p%40ss@host.frankfurt-postgres.render.com:5432/prefect",
        )

    def test_rehost_swaps_host_and_db_and_keeps_query(self) -> None:
        proc = self.derive(
            "rehost=dpg-other.virginia-postgres.render.com/mem_amaru", self.URL
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout,
            "postgresql://user:p%40ss@dpg-other.virginia-postgres.render.com:5432/mem_amaru?sslmode=require",
        )

    def test_rehost_accepts_explicit_port(self) -> None:
        proc = self.derive("rehost=ext.example:6543/otherdb", self.URL)
        self.assertEqual(
            proc.stdout,
            "postgresql://user:p%40ss@ext.example:6543/otherdb?sslmode=require",
        )

    def test_rehost_rejects_malformed_spec(self) -> None:
        self.assertEqual(self.derive("rehost=no-slash", self.URL).returncode, 3)

    def test_empty_stdin_exits_2(self) -> None:
        self.assertEqual(self.derive("self", "").returncode, 2)

    def test_unknown_transform_exits_3(self) -> None:
        proc = self.derive("nonsense=1", "x")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("unknown transform", proc.stderr)


class ReadDispatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def test_resolve_ref_literal_never_calls_op(self) -> None:
        proc = bash_lib('resolve_ref "literal:hello"', self.sb.env())
        self.assertEqual((proc.returncode, proc.stdout), (0, "hello"))
        self.assertEqual(self.sb.log_lines(), [])

    def test_plain_ref_uses_the_project_service_account_token(self) -> None:
        env = self.sb.env(
            SECRETS_SA_TOKEN_ENV="TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
            SECRETS_SA_KEYCHAIN_ITEM="op-testproj-token",
        )
        proc = bash_lib('resolve_ref "op://TESTVAULT/ITEM/value"', env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-ITEM-value")
        self.assertTrue(any(line.startswith("OP read") for line in self.sb.log_lines()))

    def test_plain_ref_without_any_token_fails_closed_no_ambient_fallback(self) -> None:
        env = self.sb.env(
            sa_token=False,
            SECRETS_SA_TOKEN_ENV="TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
            SECRETS_SA_KEYCHAIN_ITEM="op-testproj-token",
        )
        proc = bash_lib('resolve_ref "op://TESTVAULT/ITEM/value"', env)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("no project service-account token", proc.stderr)
        self.assertFalse(any(line.startswith("OP read") for line in self.sb.log_lines()))

    def test_sensitive_ref_refuses_agent_shell_before_touching_op(self) -> None:
        env = self.sb.env(CLAUDECODE="1")
        proc = bash_lib('resolve_ref "op://TESTVAULT-sensitive/SECRETX/value"', env)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("agent shell", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_sensitive_ref_escape_hatch_allows_agent_shell(self) -> None:
        env = self.sb.env(CLAUDECODE="1", SECRETS_ALLOW_AGENT="1")
        proc = bash_lib('resolve_ref "op://TESTVAULT-sensitive/SECRETX/value"', env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_non_op_ref_is_a_usage_error(self) -> None:
        proc = bash_lib('resolve_ref "https://nope"', self.sb.env())
        self.assertEqual(proc.returncode, 2)


class DbUrlTest(unittest.TestCase):
    def _run(self, snippet: str) -> subprocess.CompletedProcess[str]:
        import os
        script = f'source "{LIB}/db-url.sh"; {snippet}'
        return run(["bash", "-c", script], dict(os.environ))

    def test_without_role_option_strips_options_keeps_sslmode(self) -> None:
        proc = self._run(
            'db_url_without_role_option '
            '"postgresql://ts_root:p%40ss@host:5432/db?sslmode=require&options=-c%20role%3Dts_user"'
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout,
            "postgresql://ts_root:p%40ss@host:5432/db?sslmode=require",
        )
        self.assertNotIn("options=", proc.stdout)

    def test_without_role_option_is_noop_when_no_options(self) -> None:
        url = "postgresql://ts_root:x@host:5432/db?sslmode=require"
        proc = self._run(f'db_url_without_role_option "{url}"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, url)

    def test_parse_accepts_asyncpg_scheme(self) -> None:
        # Prefect server URLs are postgresql+asyncpg://; predecessor capture
        # and the inventory scan must read their username like any other.
        proc = self._run('db_url_username "postgresql+asyncpg://ts_app:p%40w@ext.host:5432/prefect?sslmode=require"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "ts_app")
        proc = self._run('db_parse_url "postgres://u:p@h/d" && printf "%s %s %s" "$DB_URL_PORT" "$DB_URL_DB" "$DB_URL_QUERY"')
        self.assertEqual(proc.stdout, "5432 d ")

    def test_urldecode_keeps_literal_backslashes(self) -> None:
        # printf %b used to interpret a backslash in the value (\c truncated it).
        proc = self._run('db_urldecode "a%5Cb\\c%20d"')
        self.assertEqual(proc.stdout, "a\\b\\c d")

    def test_psql_sessions_default_to_tls_and_timeouts(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "psql"
            fake.write_text("#!/usr/bin/env bash\nprintf '%s|%s|%s\\n' \"${PGSSLMODE:-}\" \"${PGOPTIONS:-}\" \"${PGUSER:-}\"\n")
            fake.chmod(0o755)
            cases = {
                "postgresql://u%40x:p@h:5432/d": "require|-c lock_timeout=15s -c statement_timeout=120s|u@x",
                "postgresql://u:p@h:5432/d?sslmode=disable&options=-c%20role%3Dr":
                    "disable|-c role=r -c lock_timeout=15s -c statement_timeout=120s|u",
            }
            for url, expected in cases.items():
                with self.subTest(url=url):
                    proc = self._run(f'PSQL_BIN="{fake}" db_run_psql_url "{url}" -q')
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout.strip(), expected)
            proc = self._run(f'DB_LOCK_TIMEOUT=3s PSQL_BIN="{fake}" db_run_psql_url "postgresql://u:p@h/d"')
            self.assertIn("lock_timeout=3s", proc.stdout)


class DeployWaitTest(unittest.TestCase):
    """A recorded deploy that Render deactivated is proven if a later deploy
    of the same service is live (batched sweep overlap)."""

    def _run(self, snippet: str) -> subprocess.CompletedProcess[str]:
        import os
        script = f'source "{LIB}/deploy-wait.sh"; {snippet}'
        env = dict(os.environ)
        env["RENDER_POLL_SECONDS"] = "0"
        env["RENDER_DEPLOY_TIMEOUT_SECONDS"] = "5"
        return run(["bash", "-c", script], env)

    def test_deactivated_id_is_proven_when_a_later_deploy_is_live(self) -> None:
        proc = self._run(r'''
render_get() {
  case "$1" in
    */deploys/dep-old) printf '{"status":"deactivated"}' ;;
    */deploys?limit=1) printf '[{"deploy":{"id":"dep-new","status":"live"}}]' ;;
    *) echo "unexpected $1" >&2; return 1 ;;
  esac
}
deploy_wait_live srv-x dep-old
''')
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("deactivated; later dep-new is live", proc.stdout)

    def test_build_failed_is_not_followed(self) -> None:
        proc = self._run(r'''
render_get() { printf '{"status":"build_failed"}'; }
deploy_wait_live srv-x dep-old
''')
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("build_failed", proc.stderr)
        self.assertNotIn("later", proc.stdout + proc.stderr)

    def test_deactivated_fails_when_later_deploy_failed(self) -> None:
        proc = self._run(r'''
render_get() {
  case "$1" in
    */deploys/dep-old) printf '{"status":"deactivated"}' ;;
    */deploys?limit=1) printf '[{"deploy":{"id":"dep-new","status":"update_failed"}}]' ;;
    *) return 1 ;;
  esac
}
deploy_wait_live srv-x dep-old
''')
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("update_failed", proc.stderr)


if __name__ == "__main__":
    unittest.main()
