from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_CONTEXT = ROOT / "bin/project-context"
RENDER_CLI = ROOT / "bin/render-cli"
REGISTRY = ROOT / "config/project-tools.json"


EXPECTED_PROJECT_REMOTES = {
    "amaru": {
        "github.com/amaru-wellness/amaru-mcp",
        "github.com/amaru-wellness/amaru-web",
        "github.com/amaru-wellness/amaru-website",
        "github.com/amaru-wellness/amaru_websites",
        "github.com/amaru-wellness/amaruplatform-website",
        "github.com/simonszalai/amaru-mobile",
    },
    "autodev": {
        "github.com/simonszalai/autodev-dashboard",
        "github.com/simonszalai/autodev-memory",
    },
    "ts": {
        "github.com/ts-value-software/ts-api",
        "github.com/ts-value-software/ts-dashboard",
        "github.com/ts-value-software/ts-decrypt-chrome-ext",
        "github.com/ts-value-software/ts-decrypt-proxy",
        "github.com/ts-value-software/ts-prefect",
        "github.com/ts-value-software/ts-scraper",
        "github.com/tssoftwareprojects/ts-mobile",
    },
    "workflow-pro": {
        "github.com/workflow-tech/workflow-pro",
        "github.com/szaboszerszam/workflow-mcp",
        "github.com/szaboszerszam/workflow-pdf",
        "github.com/szaboszerszam/workflow_pro",
    },
}

EXPECTED_SERVICE_ACCOUNT_TOKEN_ENVS = {
    "amaru": "AMARU_OP_SERVICE_ACCOUNT_TOKEN",
    "autodev": "AUTODEV_OP_SERVICE_ACCOUNT_TOKEN",
    "ts": "TS_OP_SERVICE_ACCOUNT_TOKEN",
    "workflow-pro": "WORKFLOW_PRO_OP_SERVICE_ACCOUNT_TOKEN",
}

EXPECTED_SERVICE_ACCOUNT_KEYCHAIN_ITEMS = {
    "amaru": "op-dev-token",
    "ts": "op-dev-token",
}

EXPECTED_RENDER_REFS = {
    "amaru": "op://AMARU/AMARU_RENDER_API_KEY/value",
    "autodev": "op://AUTODEV-sensitive/AUTODEV_RENDER_API_KEY/value",
    "ts": "op://TS/TS_RENDER_API_KEY/value",
    "workflow-pro": "op://WORKFLOW_PRO-sensitive/WORKFLOW_RENDER_API_KEY/value",
}


class ProjectToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "project-tools.json"
        self.config.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": {
                        "alpha": {
                            "repo_remotes": ["github.com/acme/alpha"],
                            "service_account": {
                                "token_env": "ALPHA_OP_SERVICE_ACCOUNT_TOKEN",
                                "keychain_item": "op-dev-token-alpha",
                            },
                            "render": {
                                "api_key_ref": "op://ALPHA/RENDER/value",
                                "workspace": {
                                    "discover_service_names": ["alpha-canary"]
                                },
                            },
                        },
                        "beta": {
                            "repo_remotes": ["github.com/acme/beta"],
                            "service_account": {
                                "token_env": "BETA_OP_SERVICE_ACCOUNT_TOKEN"
                            },
                            "render": {
                                "api_key_ref": "op://BETA-sensitive/RENDER/value",
                                "workspace": {"id": "tea-beta"},
                            },
                        },
                    },
                }
            )
        )
        self.repo = self.make_repo("git@github.com:acme/alpha.git")
        self.render_log = self.root / "render.log"
        self.op_log = self.root / "op.log"
        self.op_token_log = self.root / "op-token.log"
        self.tool_bin = self.root / "bin"
        self.tool_bin.mkdir()
        self.wrapper = self.tool_bin / "render-cli"
        shutil.copy2(RENDER_CLI, self.wrapper)
        shutil.copy2(PROJECT_CONTEXT, self.tool_bin / "project-context")
        self.fake_render = self.root / "render"
        self.fake_render.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" || -n "${OP_CONNECT_TOKEN:-}" ]]; then
  echo "1Password credential leaked to Render child" >&2
  exit 91
fi
printf '%s|%s|%s\\n' "${RENDER_WORKSPACE:-}" "${RENDER_API_KEY:+set}" "$*" >> "$RENDER_FAKE_LOG"
case "${1:-}" in
  workspaces)
    printf '[{"id":"tea-other"},{"id":"tea-alpha"}]\\n'
    ;;
  services)
    if [[ "${RENDER_WORKSPACE:-}" == "tea-alpha" ]]; then
      printf '[{"service":{"id":"srv-alpha","name":"alpha-canary"}}]\\n'
    else
      printf '[{"service":{"id":"srv-other","name":"other"}}]\\n'
    fi
    ;;
  *)
    printf '{"ok":true}\\n'
    ;;
esac
"""
        )
        self.fake_render.chmod(0o755)
        self.fake_op = self.tool_bin / "op"
        self.fake_op.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$RENDER_FAKE_OP_LOG"
printf '%s\\n' "${OP_SERVICE_ACCOUNT_TOKEN:-<unset>}" >> "$RENDER_FAKE_OP_TOKEN_LOG"
printf 'fake-render-key'
"""
        )
        self.fake_op.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_repo(self, remote: str) -> Path:
        repo = self.root / f"repo-{len(list(self.root.glob('repo-*')))}"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
        return repo

    def environment(self, **updates: str) -> dict[str, str]:
        env = os.environ.copy()
        for name in (
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "CODEX_THREAD_ID",
            "CODEX_CI",
            "CONDUCTOR_WORKSPACE",
            "CONDUCTOR_WORKSPACE_NAME",
            "CONDUCTOR_SESSION_ID",
            "RENDER_API_KEY",
            "OP_SERVICE_ACCOUNT_TOKEN",
            "TS_OP_SERVICE_ACCOUNT_TOKEN",
        ):
            env.pop(name, None)
        env.update(
            {
                "PROJECT_TOOLS_CONFIG": str(self.config),
                "RENDER_CLI_BIN": str(self.fake_render),
                "RENDER_FAKE_LOG": str(self.render_log),
                "RENDER_FAKE_OP_LOG": str(self.op_log),
                "RENDER_FAKE_OP_TOKEN_LOG": str(self.op_token_log),
                "ALPHA_OP_SERVICE_ACCOUNT_TOKEN": "alpha-service-account-token",
                "BETA_OP_SERVICE_ACCOUNT_TOKEN": "beta-service-account-token",
            }
        )
        env.update(updates)
        return env

    def run_context(
        self, cwd: Path, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PROJECT_CONTEXT), "--cwd", str(cwd), *arguments],
            capture_output=True,
            text=True,
            env=self.environment(),
        )

    def run_render(
        self, cwd: Path, *arguments: str, **environment: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.wrapper), *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=self.environment(**environment),
        )

    def test_committed_registry_covers_every_known_repository_once(self) -> None:
        registry = json.loads(REGISTRY.read_text())
        projects = registry["projects"]
        self.assertEqual(set(projects), set(EXPECTED_PROJECT_REMOTES))
        claimed: list[str] = []
        for project, expected in EXPECTED_PROJECT_REMOTES.items():
            actual = set(projects[project]["repo_remotes"])
            self.assertEqual(actual, expected)
            claimed.extend(actual)
            self.assertEqual(
                projects[project]["render"]["api_key_ref"],
                EXPECTED_RENDER_REFS[project],
            )
            self.assertEqual(
                projects[project]["service_account"]["token_env"],
                EXPECTED_SERVICE_ACCOUNT_TOKEN_ENVS[project],
            )
            self.assertEqual(
                projects[project]["service_account"].get("keychain_item"),
                EXPECTED_SERVICE_ACCOUNT_KEYCHAIN_ITEMS.get(project),
            )
        self.assertEqual(len(claimed), len(set(claimed)))
        token_envs = [
            projects[project]["service_account"]["token_env"] for project in projects
        ]
        self.assertEqual(len(token_envs), len(set(token_envs)))

    def test_resolver_normalizes_ssh_origin_and_fails_closed(self) -> None:
        detected = self.run_context(self.repo, "--tool", "render")
        self.assertEqual(detected.returncode, 0, detected.stderr)
        value = json.loads(detected.stdout)
        self.assertEqual(value["project"], "alpha")
        self.assertEqual(value["remote"], "github.com/acme/alpha")

        unknown = self.make_repo("https://github.com/acme/unknown.git")
        rejected = self.run_context(unknown)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("unregistered origin remote", rejected.stderr)

        mismatch = self.run_context(self.repo, "--project", "beta")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("refusing project", mismatch.stderr)
        allowed = self.run_context(
            self.repo, "--project", "beta", "--allow-cross-project"
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)["project"], "beta")

    def test_context_is_credential_free_and_reports_selected_profile(self) -> None:
        result = self.run_render(
            self.repo, "context", RENDER_CLI_BIN="/does/not/exist"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project=alpha", result.stdout)
        self.assertIn("remote=github.com/acme/alpha", result.stdout)
        self.assertIn("discover-by-service:alpha-canary", result.stdout)
        self.assertIn("op://ALPHA/RENDER/value", result.stdout)
        self.assertFalse(self.render_log.exists())
        self.assertFalse(self.op_log.exists())

    def test_nested_help_bypasses_project_and_credentials(self) -> None:
        unknown = self.make_repo("https://github.com/acme/unknown.git")
        result = self.run_render(unknown, "services", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.render_log.read_text().strip(), "||services --help")
        self.assertFalse(self.op_log.exists())

    def test_read_uses_profile_credential_and_discovers_unique_workspace(self) -> None:
        result = self.run_render(self.repo, "services")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project=alpha", result.stderr)
        self.assertIn("workspace=tea-alpha", result.stderr)
        self.assertEqual(
            self.op_log.read_text().strip(),
            "read --no-newline op://ALPHA/RENDER/value",
        )
        calls = self.render_log.read_text().splitlines()
        self.assertEqual(calls[0], "|set|workspaces -o json --confirm")
        self.assertIn("tea-alpha|set|services -o json --confirm", calls)
        self.assertEqual(calls[-1], "tea-alpha|set|services")
        self.assertNotIn("fake-render-key", result.stdout + result.stderr)
        self.assertNotIn("fake-render-key", self.render_log.read_text())

    def test_shell_trace_is_disabled_before_credentials_are_loaded(self) -> None:
        result = subprocess.run(
            ["/bin/bash", "-x", str(self.wrapper), "services"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=self.environment(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fake-render-key", result.stdout + result.stderr)

    def test_agent_shell_resolves_service_account_key_for_read(self) -> None:
        result = self.run_render(self.repo, "services", CODEX_THREAD_ID="thread")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.op_log.read_text().strip(),
            "read --no-newline op://ALPHA/RENDER/value",
        )

    def test_agent_shell_cannot_resolve_sensitive_key_without_approved_env(self) -> None:
        sensitive_repo = self.make_repo("git@github.com:acme/beta.git")
        result = self.run_render(
            sensitive_repo, "services", CODEX_THREAD_ID="thread"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("human-only", result.stderr)
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.render_log.exists())

        approved = self.run_render(
            sensitive_repo,
            "services",
            CODEX_THREAD_ID="thread",
            RENDER_API_KEY="approved-test-key",
            OP_SERVICE_ACCOUNT_TOKEN="must-not-reach-child",
            OP_CONNECT_TOKEN="must-not-reach-child",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertFalse(self.op_log.exists())

    def test_tailscale_profile_is_registry_owned_and_optional(self) -> None:
        registry = json.loads(REGISTRY.read_text())
        projects = registry["projects"]
        self.assertEqual(
            projects["ts"]["tailscale"],
            {
                "oauth_client_id_ref": "op://TS/TAILSCALE_OAUTH_CLIENT_ID_MCP/value",
                "oauth_client_secret_ref": "op://TS/TAILSCALE_OAUTH_CLIENT_SECRET_MCP/value",
            },
        )
        for project in projects:
            if project != "ts":
                self.assertNotIn("tailscale", projects[project])

        absent = self.run_context(self.repo, "--tool", "tailscale")
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn("has no 'tailscale' tool profile", absent.stderr)

        broken = self.root / "broken-tailscale.json"
        fixture = json.loads(self.config.read_text())
        fixture["projects"]["alpha"]["tailscale"] = {
            "oauth_client_id_ref": "ALPHA_TAILSCALE_ID",
            "oauth_client_secret_ref": "op://ALPHA/TAILSCALE_SECRET/value",
        }
        broken.write_text(json.dumps(fixture))
        rejected = subprocess.run(
            [str(PROJECT_CONTEXT), "--cwd", str(self.repo)],
            capture_output=True,
            text=True,
            env=self.environment(PROJECT_TOOLS_CONFIG=str(broken)),
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("tailscale.oauth_client_id_ref", rejected.stderr)

    def test_project_service_account_token_authenticates_the_credential_read(self) -> None:
        result = self.run_render(self.repo, "services")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.op_token_log.read_text().strip(), "alpha-service-account-token"
        )
        self.assertNotIn("alpha-service-account-token", result.stdout + result.stderr)
        self.assertNotIn("alpha-service-account-token", self.render_log.read_text())

    def test_unprefixed_ambient_token_is_never_a_fallback(self) -> None:
        env = self.environment()
        del env["ALPHA_OP_SERVICE_ACCOUNT_TOKEN"]
        env["OP_SERVICE_ACCOUNT_TOKEN"] = "ambient-must-not-be-used"
        env["BETA_OP_SERVICE_ACCOUNT_TOKEN"] = "wrong-project-must-not-be-used"
        result = subprocess.run(
            [str(self.wrapper), "services"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALPHA_OP_SERVICE_ACCOUNT_TOKEN", result.stderr)
        self.assertIn("project 'alpha'", result.stderr)
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.render_log.exists())

    def test_registry_rejects_unprefixed_and_duplicated_token_envs(self) -> None:
        def context_with(alpha_env: str, beta_env: str) -> subprocess.CompletedProcess[str]:
            broken = self.root / "broken.json"
            registry = json.loads(self.config.read_text())
            registry["projects"]["alpha"]["service_account"]["token_env"] = alpha_env
            registry["projects"]["beta"]["service_account"]["token_env"] = beta_env
            broken.write_text(json.dumps(registry))
            env = self.environment(PROJECT_TOOLS_CONFIG=str(broken))
            return subprocess.run(
                [str(PROJECT_CONTEXT), "--cwd", str(self.repo)],
                capture_output=True,
                text=True,
                env=env,
            )

        unprefixed = context_with(
            "OP_SERVICE_ACCOUNT_TOKEN", "BETA_OP_SERVICE_ACCOUNT_TOKEN"
        )
        self.assertNotEqual(unprefixed.returncode, 0)
        self.assertIn("project-prefixed", unprefixed.stderr)

        duplicated = context_with(
            "SHARED_OP_SERVICE_ACCOUNT_TOKEN", "SHARED_OP_SERVICE_ACCOUNT_TOKEN"
        )
        self.assertNotEqual(duplicated.returncode, 0)
        self.assertIn("belongs to both", duplicated.stderr)

    def test_mutations_require_explicit_matching_project_write_and_reason(self) -> None:
        implicit = self.run_render(self.repo, "--write", "--reason", "test", "restart", "srv")
        self.assertNotEqual(implicit.returncode, 0)
        self.assertIn("explicit --project", implicit.stderr)
        self.assertFalse(self.op_log.exists())

        no_reason = self.run_render(
            self.repo, "--project", "alpha", "--write", "restart", "srv"
        )
        self.assertNotEqual(no_reason.returncode, 0)
        self.assertIn("--reason", no_reason.stderr)

        hidden_subcommand = self.run_render(
            self.repo, "services", "--output", "json", "delete", "srv"
        )
        self.assertNotEqual(hidden_subcommand.returncode, 0)
        self.assertIn("command is mutating", hidden_subcommand.stderr)

        wrong = self.run_render(
            self.repo,
            "--project",
            "beta",
            "--write",
            "--reason",
            "test",
            "restart",
            "srv",
        )
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("refusing project", wrong.stderr)

        accepted = self.run_render(
            self.repo,
            "--project",
            "alpha",
            "--write",
            "--reason",
            "test mutation",
            "restart",
            "srv",
            RENDER_API_KEY="approved-test-key",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(
            self.render_log.read_text().splitlines()[-1],
            "tea-alpha|set|restart srv",
        )


if __name__ == "__main__":
    unittest.main()
