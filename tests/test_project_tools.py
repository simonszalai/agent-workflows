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
PSQL_CLI = ROOT / "bin/psql-cli"
SLACK_API = ROOT / "bin/slack-api"
RESEND_CLI = ROOT / "bin/resend-cli"
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
    "amaru": "op-amaru-token",
    "autodev": "op-autodev-token",
    "ts": "op-ts-token",
    "workflow-pro": "op-workflow-pro-token",
}

EXPECTED_RENDER_REFS = {
    "amaru": "op://AMARU/AMARU_RENDER_API_KEY/value",
    "autodev": "op://AUTODEV-sensitive/AUTODEV_RENDER_API_KEY/value",
    "ts": "op://TS/TS_RENDER_API_KEY/value",
    "workflow-pro": "op://WORKFLOW_PRO/WORKFLOW_RENDER_API_KEY/value",
}

EXPECTED_AUTODEV_MEMORY_PROFILES = {
    "amaru": {
        "route": "amaru",
        "token_ref": "op://AMARU/AMARU_AUTODEV_MEMORY_API_TOKEN/value",
    },
    "autodev": {
        "route": "autodev",
        "token_ref": "op://AUTODEV/AUTODEV_AUTODEV_MEMORY_API_TOKEN/value",
    },
    "ts": {
        "route": "ts",
        "token_ref": "op://TS/TS_AUTODEV_MEMORY_API_TOKEN/value",
    },
    "workflow-pro": {
        "route": "workflow-pro",
        "token_ref": "op://WORKFLOW_PRO/WORKFLOW_PRO_AUTODEV_MEMORY_API_TOKEN/value",
    },
}

EXPECTED_POSTGRES_REFS = {
    "amaru": {
        "dev": "op://AMARU/DEV_POSTGRES_URL/value",
        "staging": "op://AMARU/STAGING_POSTGRES_URL_RO/value",
        "prod": "op://AMARU/PROD_POSTGRES_URL_RO/value",
    },
    "ts": {
        "dev": "op://TS/DEV_POSTGRES_URL/value",
        "staging": "op://TS/STAGING_POSTGRES_URL/value",
        "prod": "op://TS/PROD_POSTGRES_URL_RO/value",
    },
    "workflow-pro": {
        "dev": "op://WORKFLOW_PRO/DEV_POSTGRES_URL/value",
        "staging": "op://WORKFLOW_PRO/STAGING_POSTGRES_URL/value",
    },
}

EXPECTED_RESEND_REFS = {
    "amaru": "op://AMARU/RESEND_API_KEY/value",
}

EXPECTED_RESEND_CANARY_DOMAINS = {
    "amaru": "amaruplatform.com",
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
                            "autodev_memory": {
                                "route": "alpha",
                                "token_ref": "op://ALPHA/AUTODEV_MEMORY/value",
                            },
                            "render": {
                                "api_key_ref": "op://ALPHA/RENDER/value",
                                "workspace": {
                                    "discover_service_names": ["alpha-canary"]
                                },
                            },
                            "postgres": {
                                "tiers": {
                                    "dev": {"dsn_ref": "op://ALPHA/DEV_DATABASE/value"},
                                    "staging": {
                                        "dsn_ref": "op://ALPHA/STAGING_DATABASE/value"
                                    },
                                }
                            },
                            "slack": {"token_ref": "op://ALPHA/SLACK_TOKEN/value"},
                            "resend": {
                                "api_key_ref": "op://ALPHA/RESEND/value",
                                "canary_domain": "alpha.example.com",
                            },
                        },
                        "beta": {
                            "repo_remotes": ["github.com/acme/beta"],
                            "service_account": {
                                "token_env": "BETA_OP_SERVICE_ACCOUNT_TOKEN"
                            },
                            "autodev_memory": {
                                "route": "beta",
                                "token_ref": "op://BETA/AUTODEV_MEMORY/value",
                            },
                            "render": {
                                "api_key_ref": "op://BETA-sensitive/RENDER/value",
                                "workspace": {"id": "tea-beta"},
                            },
                            "postgres": {
                                "tiers": {
                                    "dev": {"dsn_ref": "op://BETA/DEV_DATABASE/value"}
                                }
                            },
                            "resend": {
                                "api_key_ref": "op://BETA-sensitive/RESEND/value",
                                "canary_domain": "beta.example.com",
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
        self.resend_wrapper = self.tool_bin / "resend-cli"
        shutil.copy2(RESEND_CLI, self.resend_wrapper)
        shutil.copy2(PROJECT_CONTEXT, self.tool_bin / "project-context")
        self.psql_wrapper = self.tool_bin / "psql-cli"
        shutil.copy2(PSQL_CLI, self.psql_wrapper)
        self.slack_wrapper = self.tool_bin / "slack-api"
        shutil.copy2(SLACK_API, self.slack_wrapper)
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
        self.resend_log = self.root / "resend.log"
        self.fake_resend = self.root / "resend"
        self.fake_resend.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" || -n "${OP_CONNECT_TOKEN:-}" ]]; then
  echo "1Password credential leaked to Resend child" >&2
  exit 91
fi
printf '%s|%s\\n' "${RESEND_API_KEY:+set}" "$*" >> "$RESEND_FAKE_LOG"
if [[ "${1:-} ${2:-}" == "domains list" ]]; then
  printf '{"data":[{"name":"%s"}]}\\n' "${RESEND_FAKE_DOMAIN:-alpha.example.com}"
elif [[ "${1:-}" == "doctor" ]]; then
  printf '{"ok":true,"key":"re_masked"}\\n'
else
  printf '{"ok":true}\\n'
fi
"""
        )
        self.fake_resend.chmod(0o755)
        self.fake_op = self.tool_bin / "op"
        self.fake_op.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$RENDER_FAKE_OP_LOG"
printf '%s\\n' "${OP_SERVICE_ACCOUNT_TOKEN:-<unset>}" >> "$RENDER_FAKE_OP_TOKEN_LOG"
case "$*" in
  *DATABASE*) printf 'postgresql://fake-user:fake-password@fake.invalid/database' ;;
  *SLACK_TOKEN*) printf 'xoxp-fake-slack-token' ;;
  *) printf 'fake-render-key' ;;
esac
"""
        )
        self.fake_op.chmod(0o755)
        self.psql_log = self.root / "psql.log"
        self.psql_input_log = self.root / "psql-input.log"
        self.fake_psql = self.root / "psql"
        self.fake_psql.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
if [[ "${PGHOST:-}" != "fake.invalid" || "${PGPORT:-}" != "5432" || \
      "${PGDATABASE:-}" != "database" || "${PGUSER:-}" != "fake-user" || \
      "${PGPASSWORD:-}" != "fake-password" ]]; then
  echo "unexpected or missing parsed PostgreSQL connection variables" >&2
  exit 90
fi
if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}${OP_CONNECT_HOST:-}${OP_CONNECT_TOKEN:-}${OP_SESSION_TEST:-}${ALPHA_OP_SERVICE_ACCOUNT_TOKEN:-}${BETA_OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
  echo "1Password credential leaked to psql child" >&2
  exit 91
fi
printf 'args=' >> "$PSQL_FAKE_LOG"
printf '<%s>' "$@" >> "$PSQL_FAKE_LOG"
printf '\\nPGDATABASE=set\\nPGPASSWORD=set\\nPGOPTIONS=%s\\nPGCONNECT_TIMEOUT=%s\\n' \
  "${PGOPTIONS:-}" "${PGCONNECT_TIMEOUT:-}" >> "$PSQL_FAKE_LOG"
cat > "$PSQL_FAKE_INPUT_LOG"
if [[ -n "${PSQL_FAKE_BYTES:-}" ]]; then
  head -c "$PSQL_FAKE_BYTES" /dev/zero | tr '\\0' x
else
  printf 'answer\\n42\\n'
fi
exit "${PSQL_FAKE_STATUS:-0}"
"""
        )
        self.fake_psql.chmod(0o755)
        self.curl_log = self.root / "curl.log"
        self.fake_curl = self.tool_bin / "curl"
        self.fake_curl.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}${OP_CONNECT_HOST:-}${OP_CONNECT_TOKEN:-}${OP_SESSION_TEST:-}${ALPHA_OP_SERVICE_ACCOUNT_TOKEN:-}${BETA_OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
  echo "1Password credential leaked to curl child" >&2
  exit 91
fi
printf '%s\\n' "$*" > "$SLACK_FAKE_CURL_LOG"
previous=""
for argument in "$@"; do
  if [[ "$previous" == "-H" && "$argument" == @* ]]; then
    header="$(cat "${argument#@}")"
    [[ "$header" == "Authorization: Bearer xoxp-fake-slack-token" ]] || exit 92
    printf 'header=set\\n' >> "$SLACK_FAKE_CURL_LOG"
  fi
  previous="$argument"
done
printf '{"ok":true}\\n'
"""
        )
        self.fake_curl.chmod(0o755)

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
            "RESEND_API_KEY",
            "OP_SERVICE_ACCOUNT_TOKEN",
            "TS_OP_SERVICE_ACCOUNT_TOKEN",
            "ALPHA_OP_SERVICE_ACCOUNT_TOKEN",
            "BETA_OP_SERVICE_ACCOUNT_TOKEN",
        ):
            env.pop(name, None)
        env.update(
            {
                "PROJECT_TOOLS_CONFIG": str(self.config),
                "RENDER_CLI_BIN": str(self.fake_render),
                "RENDER_FAKE_LOG": str(self.render_log),
                "RENDER_FAKE_OP_LOG": str(self.op_log),
                "RENDER_FAKE_OP_TOKEN_LOG": str(self.op_token_log),
                "RESEND_CLI_BIN": str(self.fake_resend),
                "RESEND_FAKE_LOG": str(self.resend_log),
                "ALPHA_OP_SERVICE_ACCOUNT_TOKEN": "alpha-service-account-token",
                "BETA_OP_SERVICE_ACCOUNT_TOKEN": "beta-service-account-token",
                "PSQL_CLI_BIN": str(self.fake_psql),
                "PSQL_FAKE_LOG": str(self.psql_log),
                "PSQL_FAKE_INPUT_LOG": str(self.psql_input_log),
                "SLACK_FAKE_CURL_LOG": str(self.curl_log),
                "PATH": f"{self.tool_bin}:{env.get('PATH', '')}",
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

    def run_psql(
        self, cwd: Path, *arguments: str, **environment: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.psql_wrapper), *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=self.environment(**environment),
        )

    def run_slack(
        self, cwd: Path, *arguments: str, **environment: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.slack_wrapper), *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=self.environment(**environment),
        )

    def run_resend(
        self, cwd: Path, *arguments: str, **environment: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.resend_wrapper), *arguments],
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
            self.assertEqual(
                projects[project]["autodev_memory"],
                EXPECTED_AUTODEV_MEMORY_PROFILES[project],
            )
            self.assertEqual(
                projects[project].get("resend", {}).get("api_key_ref"),
                EXPECTED_RESEND_REFS.get(project),
            )
            self.assertEqual(
                projects[project].get("resend", {}).get("canary_domain"),
                EXPECTED_RESEND_CANARY_DOMAINS.get(project),
            )
        self.assertEqual(len(claimed), len(set(claimed)))
        token_envs = [
            projects[project]["service_account"]["token_env"] for project in projects
        ]
        self.assertEqual(len(token_envs), len(set(token_envs)))
        self.assertEqual(
            {
                project: {
                    tier: profile["dsn_ref"]
                    for tier, profile in projects[project]["postgres"]["tiers"].items()
                }
                for project in EXPECTED_POSTGRES_REFS
            },
            EXPECTED_POSTGRES_REFS,
        )
        self.assertNotIn("postgres", projects["autodev"])
        self.assertEqual(
            projects["ts"]["slack"],
            {"token_ref": "op://TS/TS_SLACK_MCP_USER_TOKEN/value"},
        )
        for project in projects:
            if project != "ts":
                self.assertNotIn("slack", projects[project])

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

    def test_postgres_and_slack_profiles_are_strictly_validated(self) -> None:
        def rejected(mutator) -> subprocess.CompletedProcess[str]:
            broken = self.root / "broken-tools.json"
            fixture = json.loads(self.config.read_text())
            mutator(fixture)
            broken.write_text(json.dumps(fixture))
            return subprocess.run(
                [str(PROJECT_CONTEXT), "--list-projects"],
                capture_output=True,
                text=True,
                env=self.environment(PROJECT_TOOLS_CONFIG=str(broken)),
            )

        cases = (
            (
                lambda value: value["projects"]["alpha"].__setitem__(
                    "postgres", None
                ),
                "postgres must be an object",
            ),
            (
                lambda value: value["projects"]["alpha"]["postgres"].update(
                    tiers={}
                ),
                "non-empty object",
            ),
            (
                lambda value: value["projects"]["alpha"]["postgres"]["tiers"].update(
                    {"Prod DB": {"dsn_ref": "op://ALPHA/PROD/value"}}
                ),
                "invalid tier id",
            ),
            (
                lambda value: value["projects"]["alpha"]["postgres"].update(
                    fallback="dev"
                ),
                "unknown keys",
            ),
            (
                lambda value: value["projects"]["alpha"]["postgres"]["tiers"][
                    "dev"
                ].update(database="alpha"),
                "unknown keys",
            ),
            (
                lambda value: value["projects"]["alpha"]["postgres"]["tiers"][
                    "dev"
                ].update(dsn_ref="ALPHA_DATABASE_URL"),
                "canonical op://",
            ),
            (
                lambda value: value["projects"]["alpha"]["postgres"]["tiers"][
                    "dev"
                ].update(dsn_ref="op://ALPHA-sensitive/DATABASE/value"),
                "must not reference",
            ),
            (
                lambda value: value["projects"]["alpha"]["slack"].update(
                    token_ref="op://ALPHA-sensitive/SLACK/value"
                ),
                "must not reference",
            ),
            (
                lambda value: value["projects"]["alpha"]["slack"].update(
                    workspace="alpha"
                ),
                "unknown keys",
            ),
            (
                lambda value: value["projects"]["alpha"].__setitem__("slack", None),
                "slack must be an object",
            ),
        )
        for mutator, message in cases:
            with self.subTest(message=message):
                result = rejected(mutator)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_psql_context_is_credential_free_and_tier_selection_is_exact(self) -> None:
        context = self.run_psql(
            self.repo, "context", "staging", PSQL_CLI_BIN="/does/not/exist"
        )
        self.assertEqual(context.returncode, 0, context.stderr)
        self.assertIn("project=alpha", context.stdout)
        self.assertIn("remote=github.com/acme/alpha", context.stdout)
        self.assertIn("tier=staging", context.stdout)
        self.assertIn(
            "credential_ref=op://ALPHA/STAGING_DATABASE/value", context.stdout
        )
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.psql_log.exists())

        missing = self.run_psql(self.repo, "prod", "SELECT 1")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("tier 'prod' is not configured", missing.stderr)
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.psql_log.exists())

    def test_psql_missing_profile_fails_closed(self) -> None:
        fixture = json.loads(self.config.read_text())
        del fixture["projects"]["alpha"]["postgres"]
        missing = self.root / "missing-postgres.json"
        missing.write_text(json.dumps(fixture))
        result = self.run_psql(
            self.repo,
            "dev",
            "SELECT 1",
            PROJECT_TOOLS_CONFIG=str(missing),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no 'postgres' tool profile", result.stderr)
        self.assertFalse(self.op_log.exists())

    def test_psql_uses_exact_project_ref_and_service_account(self) -> None:
        alpha = self.run_psql(self.repo, "dev", "SELECT 1")
        self.assertEqual(alpha.returncode, 0, alpha.stderr)
        self.assertEqual(
            self.op_log.read_text().strip(),
            "read --no-newline op://ALPHA/DEV_DATABASE/value",
        )
        self.assertEqual(
            self.op_token_log.read_text().strip(), "alpha-service-account-token"
        )

        self.op_log.unlink()
        self.op_token_log.unlink()
        beta = self.run_psql(
            self.repo,
            "--project",
            "beta",
            "--allow-cross-project",
            "dev",
            "SELECT 2",
        )
        self.assertEqual(beta.returncode, 0, beta.stderr)
        self.assertEqual(
            self.op_log.read_text().strip(),
            "read --no-newline op://BETA/DEV_DATABASE/value",
        )
        self.assertEqual(
            self.op_token_log.read_text().strip(), "beta-service-account-token"
        )

    def test_psql_never_uses_ambient_or_wrong_project_service_account(self) -> None:
        env = self.environment()
        del env["ALPHA_OP_SERVICE_ACCOUNT_TOKEN"]
        env["OP_SERVICE_ACCOUNT_TOKEN"] = "ambient-must-not-be-used"
        env["BETA_OP_SERVICE_ACCOUNT_TOKEN"] = "wrong-project-must-not-be-used"
        result = subprocess.run(
            [str(self.psql_wrapper), "dev", "SELECT 1"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALPHA_OP_SERVICE_ACCOUNT_TOKEN", result.stderr)
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.psql_log.exists())

    def test_psql_hides_dsn_and_op_credentials_and_enforces_read_only_session(self) -> None:
        result = self.run_psql(
            self.repo,
            "dev",
            "SELECT 42;",
            OP_CONNECT_HOST="ambient-connect-host",
            OP_CONNECT_TOKEN="ambient-connect-token",
            OP_SESSION_TEST="ambient-session-token",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        secret = "postgresql://fake-user:fake-password@fake.invalid/database"
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertNotIn(secret, self.psql_log.read_text())
        log = self.psql_log.read_text()
        self.assertIn(
            "args=<-X><-q><-v><ON_ERROR_STOP=1><--csv><-P><pager=off>", log
        )
        self.assertIn(
            "PGOPTIONS=-c statement_timeout=30000 -c default_transaction_read_only=on",
            log,
        )
        self.assertIn("PGCONNECT_TIMEOUT=15", log)
        session = self.psql_input_log.read_text()
        self.assertEqual(session, "BEGIN READ ONLY;\nSELECT 42;\nCOMMIT;\n")

    def test_psql_disables_shell_trace_before_loading_secrets(self) -> None:
        result = subprocess.run(
            ["/bin/bash", "-x", str(self.psql_wrapper), "dev", "SELECT 1"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=self.environment(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        combined = result.stdout + result.stderr
        self.assertNotIn("fake-password", combined)
        self.assertNotIn("alpha-service-account-token", combined)

    def test_psql_rejects_mutation_and_multiple_statements_before_credentials(self) -> None:
        rejected_queries = (
            "UPDATE widgets SET name = 'bad'",
            "DELETE FROM widgets",
            "SELECT 1; SELECT 2",
            "SELECT ';'",
            "  /* comment */ INSERT INTO widgets VALUES (1)",
        )
        for query in rejected_queries:
            with self.subTest(query=query):
                result = self.run_psql(self.repo, "dev", query)
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.psql_log.exists())

    def test_psql_validates_output_cap_before_credentials(self) -> None:
        for cap in ("0", "65537", "1.5", "bytes"):
            with self.subTest(cap=cap):
                result = self.run_psql(
                    self.repo,
                    "dev",
                    "SELECT 1",
                    PSQL_CLI_MAX_BYTES=cap,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("integer from 1 to 65536", result.stderr)
        self.assertFalse(self.op_log.exists())

    def test_psql_missing_binary_gives_install_advice_before_credentials(self) -> None:
        result = self.run_psql(
            self.repo, "dev", "SELECT 1", PSQL_CLI_BIN="/missing/psql"
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("psql is not installed", result.stderr)
        self.assertIn("Install", result.stderr)
        self.assertFalse(self.op_log.exists())

    def test_psql_truncates_output_and_preserves_psql_exit_status(self) -> None:
        result = self.run_psql(
            self.repo,
            "dev",
            "SELECT 1",
            PSQL_CLI_MAX_BYTES="64",
            PSQL_FAKE_BYTES="200",
            PSQL_FAKE_STATUS="7",
        )
        self.assertEqual(result.returncode, 7)
        self.assertTrue(result.stdout.startswith("x" * 64))
        self.assertIn("TRUNCATED at 64 bytes", result.stdout)
        self.assertNotIn("x" * 65, result.stdout)

    def test_psql_search_escapes_term_and_is_deterministic_and_bounded(self) -> None:
        term = "user_%'; DROP TABLE widgets; --\\name"
        result = self.run_psql(self.repo, "dev", "search", term)
        self.assertEqual(result.returncode, 0, result.stderr)
        query = self.psql_input_log.read_text()
        self.assertIn("pg_catalog.pg_namespace", query)
        self.assertIn("pg_catalog.pg_class", query)
        self.assertIn("pg_catalog.pg_index", query)
        self.assertIn("pg_catalog.pg_proc", query)
        self.assertIn("ORDER BY object_type, schema_name, object_name", query)
        self.assertIn("LIMIT 100", query)
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace(
            "_", "\\_"
        )
        self.assertIn(escaped.encode().hex(), query)
        self.assertNotIn("DROP TABLE widgets", query)
        self.assertIn("ESCAPE chr(92)", query)
        self.assertEqual(query.count("BEGIN READ ONLY;"), 1)
        self.assertEqual(query.count("COMMIT;"), 1)

    def test_slack_uses_registry_profile_and_fails_closed_without_one(self) -> None:
        accepted = self.run_slack(
            self.repo,
            "conversations.list",
            "types=public_channel",
            "limit=20",
            OP_CONNECT_HOST="ambient-connect-host",
            OP_CONNECT_TOKEN="ambient-connect-token",
            OP_SESSION_TEST="ambient-session-token",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout), {"ok": True})
        self.assertEqual(
            self.op_log.read_text().strip(),
            "read --no-newline op://ALPHA/SLACK_TOKEN/value",
        )
        self.assertEqual(
            self.op_token_log.read_text().strip(), "alpha-service-account-token"
        )
        curl_call = self.curl_log.read_text()
        self.assertIn("https://slack.com/api/conversations.list", curl_call)
        self.assertIn("header=set", curl_call)
        self.assertNotIn("xoxp-fake-slack-token", curl_call)

        self.op_log.unlink()
        beta_repo = self.make_repo("git@github.com:acme/beta.git")
        rejected = self.run_slack(beta_repo, "conversations.list")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("has no 'slack' tool profile", rejected.stderr)
        self.assertFalse(self.op_log.exists())

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

    def test_resend_context_is_credential_free(self) -> None:
        result = self.run_resend(
            self.repo, "context", RESEND_CLI_BIN="/does/not/exist"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project=alpha", result.stdout)
        self.assertIn("remote=github.com/acme/alpha", result.stdout)
        self.assertIn("canary_domain=alpha.example.com", result.stdout)
        self.assertIn("op://ALPHA/RESEND/value", result.stdout)
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.resend_log.exists())

    def test_resend_read_injects_only_selected_key_and_forces_json(self) -> None:
        result = self.run_resend(self.repo, "domains", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project=alpha", result.stderr)
        self.assertEqual(
            self.op_log.read_text().strip(),
            "read --no-newline op://ALPHA/RESEND/value",
        )
        self.assertEqual(
            self.resend_log.read_text().splitlines(),
            ["set|domains list --json", "set|domains list --json"],
        )
        self.assertNotIn("fake-render-key", result.stdout + result.stderr)

    def test_resend_mutations_require_project_write_and_reason(self) -> None:
        implicit = self.run_resend(
            self.repo, "--write", "--reason", "test", "emails", "send"
        )
        self.assertNotEqual(implicit.returncode, 0)
        self.assertIn("explicit --project", implicit.stderr)
        self.assertFalse(self.op_log.exists())

        no_reason = self.run_resend(
            self.repo, "--project", "alpha", "--write", "emails", "send"
        )
        self.assertNotEqual(no_reason.returncode, 0)
        self.assertIn("--reason", no_reason.stderr)

        accepted = self.run_resend(
            self.repo,
            "--project",
            "alpha",
            "--write",
            "--reason",
            "approved test",
            "emails",
            "send",
            RESEND_API_KEY="approved-test-key",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(
            self.resend_log.read_text().splitlines()[-1], "set|emails send --json"
        )

    def test_resend_rejects_profile_overrides_and_persistent_auth(self) -> None:
        override = self.run_resend(self.repo, "domains", "list", "--api-key", "bad")
        self.assertNotEqual(override.returncode, 0)
        self.assertIn("overrides are forbidden", override.stderr)
        self.assertFalse(self.op_log.exists())

        login = self.run_resend(self.repo, "login")
        self.assertNotEqual(login.returncode, 0)
        self.assertIn("saved Resend authentication is forbidden", login.stderr)
        self.assertFalse(self.op_log.exists())

        dashboard = self.run_resend(self.repo, "domains", "open")
        self.assertNotEqual(dashboard.returncode, 0)
        self.assertIn("cannot enforce the selected project", dashboard.stderr)

    def test_resend_api_key_creation_is_always_blocked(self) -> None:
        result = self.run_resend(
            self.repo,
            "--project",
            "alpha",
            "--write",
            "--reason",
            "test",
            "api-keys",
            "create",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("emits a new secret", result.stderr)
        self.assertFalse(self.op_log.exists())

    def test_resend_agent_shell_rejects_sensitive_profile_without_approved_env(self) -> None:
        sensitive_repo = self.make_repo("git@github.com:acme/beta.git")
        result = self.run_resend(
            sensitive_repo, "domains", "list", CODEX_THREAD_ID="thread"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("human-only", result.stderr)
        self.assertFalse(self.op_log.exists())
        self.assertFalse(self.resend_log.exists())

        approved = self.run_resend(
            sensitive_repo,
            "domains",
            "list",
            CODEX_THREAD_ID="thread",
            RESEND_API_KEY="approved-test-key",
            OP_SERVICE_ACCOUNT_TOKEN="must-not-reach-child",
            OP_CONNECT_TOKEN="must-not-reach-child",
            RESEND_FAKE_DOMAIN="beta.example.com",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)

    def test_resend_doctor_does_not_echo_provider_output(self) -> None:
        result = self.run_resend(self.repo, "doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("resend-cli doctor: OK project=alpha", result.stdout)
        self.assertNotIn("re_masked", result.stdout + result.stderr)

    def test_resend_rejects_a_credential_for_the_wrong_account(self) -> None:
        result = self.run_resend(
            self.repo,
            "domains",
            "list",
            RESEND_API_KEY="wrong-account-key",
            RESEND_FAKE_DOMAIN="other.example.com",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("registered canary domain", result.stderr)

    def test_registry_rejects_invalid_resend_profile(self) -> None:
        broken = self.root / "broken-resend.json"
        registry = json.loads(self.config.read_text())
        registry["projects"]["alpha"]["resend"]["api_key_ref"] = "RESEND_API_KEY"
        broken.write_text(json.dumps(registry))
        rejected = subprocess.run(
            [str(PROJECT_CONTEXT), "--cwd", str(self.repo)],
            capture_output=True,
            text=True,
            env=self.environment(PROJECT_TOOLS_CONFIG=str(broken)),
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("resend.api_key_ref", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
