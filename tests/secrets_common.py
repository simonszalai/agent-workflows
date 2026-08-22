"""Shared sandbox fixture for the secrets-engine tests.

Builds a TemporaryDirectory containing a synthetic consumer repo (git remote
registered in a synthetic project-tools config), a routing manifest, and fake
`op`/`gh`/`curl`/`security` executables that log argv (NEVER values) and exit
91 if a secret value ever reaches their argv.
"""

from __future__ import annotations

import os
import subprocess

import yaml
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SHELL_FILES = (
    "bin/sync-secrets",
    "bin/rotate-secret",
    "bin/dev-env",
    "bin/import-render-env",
    "bin/with-dev-env",
    "secrets/lib/config.sh",
    "secrets/lib/provider-common.sh",
    "secrets/lib/deploy-wait.sh",
    "secrets/lib/read.sh",
    "secrets/lib/derive.sh",
    "secrets/lib/render-api.sh",
    "secrets/lib/vault.sh",
    "secrets/lib/writer-common.sh",
    "secrets/lib/db-url.sh",
    "secrets/lib/db-rotation.sh",
    "secrets/lib/writers/github",
    "secrets/lib/writers/render",
    "secrets/lib/writers/prefect",
    "secrets/lib/writers/hermes",
    "secrets/providers/self_minted.sh",
    "secrets/providers/manual.sh",
    "secrets/providers/postgres.sh",
    "secrets/providers/postgres-rotate",
    "secrets/providers/resend.sh",
    "secrets/providers/openai.sh",
    "secrets/providers/aws_iam.sh",
)

AGENT_MARKERS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CODEX_THREAD_ID",
    "CODEX_CI",
    "CODEX_WORKING_DIR",
)

SA_TOKEN_SENTINEL = "SENTINEL_SA_TOKEN_9c41"

PROJECT_TOOLS = textwrap.dedent(
    """\
    {
      "schema_version": 1,
      "projects": {
        "testproj": {
          "repo_remotes": ["github.com/testorg/testrepo"],
          "service_account": {
            "token_env": "TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
            "keychain_item": "op-testproj-token"
          },
          "autodev_memory": {
            "url": "https://autodev-memory.onrender.com",
            "token_ref": "op://TESTVAULT/TESTPROJ_AUTODEV_MEMORY_API_TOKEN/value"
          },
          "render": {
            "api_key_ref": "op://TESTVAULT/TEST_RENDER_API_KEY/value",
            "workspace": {"discover_service_names": ["svc-a"]}
          }
        }
      }
    }
    """
)

# Interleaved services on purpose: deploy-last must still group correctly.
MANIFEST = "\n".join(
    [
        "# synthetic manifest",
        "github\ttestorg/testrepo\tGH_TOKEN_A\top://TESTVAULT/ITEM/value\tself",
        "render\tsrv-alpha\tALPHA_ONE\top://TESTVAULT/ITEM/value\tself",
        "render\tsrv-beta\tBETA_ONE\top://TESTVAULT/ITEM2/value\tself",
        "render\tsrv-alpha\tALPHA_TWO\top://TESTVAULT/OTHER/value\tself",
        "render\tsrv-beta\tBETA_LIT\tliteral:plain-config\tself",
        "prefect\tstaging\tPF_ONE\top://TESTVAULT/ITEM/value\tself",
        "dev\ttestprofile\tDEV_ONE\top://TESTVAULT/ITEM/value\tself",
        "",
    ]
)

SENSITIVE_MANIFEST = "\n".join(
    [
        "render\tsrv-alpha\tSECRET_X\top://TESTVAULT-sensitive/SECRETX/value\tself",
        "",
    ]
)

FAKE_OP = r"""#!/usr/bin/env bash
set -uo pipefail
for a in "$@"; do
  case "$a" in val-*|SENTINEL_*) echo "LEAK: secret value on op argv" >&2; exit 91 ;; esac
done
printf 'OP %s\n' "$*" >> "$FAKE_LOG"
state="${FAKE_OP_STATE:?}"
resolve_value() { # op://v/i/f -> synthetic or stored value on stdout
  local ref="$1" rest v i f file
  rest="${ref#op://}"; v="${rest%%/*}"; rest="${rest#*/}"; i="${rest%%/*}"; f="${rest#*/}"
  file="$state/${v}__${i}__${f}"
  if [[ -f "$file" ]]; then
    cat "$file"
  else
    case "$ref" in
      *EMPTY_ITEM*) ;;
      *) printf 'val-%s-%s' "$i" "$f" ;;
    esac
  fi
}
cmd="${1:-}"
case "$cmd" in
  read)
    ref=""
    for a in "$@"; do case "$a" in op://*) ref="$a" ;; esac; done
    resolve_value "$ref"
    ;;
  inject)
    while IFS= read -r line; do
      if [[ "$line" =~ \{\{\ (op://[^}\ ]*)\ \}\} ]]; then
        printf '%s=%s\n' "${line%%=*}" "$(resolve_value "${BASH_REMATCH[1]}")"
      else
        printf '%s\n' "$line"
      fi
    done
    ;;
  item)
    sub="${2:-}"
    case "$sub" in
      list)
        vault=""; prev=""
        for a in "$@"; do [[ "$prev" == "--vault" ]] && vault="$a"; prev="$a"; done
        printf '['
        first=1; seen=" "
        for fpath in "$state/${vault}__"*; do
          [[ -e "$fpath" ]] || continue
          base="$(basename "$fpath")"
          title="${base#"${vault}"__}"; title="${title%%__*}"
          case "$seen" in *" $title "*) continue ;; esac   # one item per title (multi-field items)
          seen="$seen$title "
          [[ $first -eq 1 ]] || printf ','
          printf '{"id":"id-%s","title":"%s"}' "$title" "$title"
          first=0
        done
        printf ']\n'
        ;;
      create)
        json="$(cat)"
        vault="$(jq -r '.vault.name' <<<"$json")"
        title="$(jq -r '.title' <<<"$json")"
        while IFS= read -r field; do
          jq -r --arg f "$field" '.fields[] | select(.label == $f) | .value' <<<"$json" \
            | tr -d '\n' > "$state/${vault}__${title}__${field}"
        done < <(jq -r '.fields[].label' <<<"$json")
        printf '{"id":"id-%s"}\n' "$title"
        ;;
      get)
        id="${3:-}"; vault=""; prev=""
        for a in "$@"; do [[ "$prev" == "--vault" ]] && vault="$a"; prev="$a"; done
        title="${id#id-}"
        found=0; fields='[]'
        for fpath in "$state/${vault}__${title}__"*; do
          [[ -e "$fpath" ]] || continue
          found=1
          base="$(basename "$fpath")"; field="${base##*__}"
          fields="$(jq --arg f "$field" --rawfile v "$fpath" '. + [{label:$f, value:$v}]' <<<"$fields")"
        done
        [[ $found -eq 1 ]] || { echo "fake op: item not found" >&2; exit 1; }
        jq -n --arg id "id-$title" --arg title "$title" --argjson fields "$fields" \
          '{id:$id,title:$title,fields:$fields}'
        ;;
      edit)
        id="${3:-}"; vault=""; prev=""
        for a in "$@"; do [[ "$prev" == "--vault" ]] && vault="$a"; prev="$a"; done
        title="${id#id-}"
        json="$(cat)"
        # Simulate 1Password 409 Conflict for the first N edits (concurrency).
        if [[ -n "${FAKE_OP_EDIT_CONFLICTS:-}" ]]; then
          conflict_count_file="$state/.edit-conflicts"
          n="$(cat "$conflict_count_file" 2>/dev/null || echo 0)"
          if [[ "$n" -lt "$FAKE_OP_EDIT_CONFLICTS" ]]; then
            echo $((n + 1)) > "$conflict_count_file"
            echo "[ERROR] unable to process line 1: DB: (409) (Conflict), Internal server conflict." >&2
            exit 1
          fi
        fi
        while IFS= read -r field; do
          jq -r --arg f "$field" '.fields[] | select(.label == $f) | .value' <<<"$json" \
            | tr -d '\n' > "$state/${vault}__${title}__${field}"
        done < <(jq -r '.fields[].label' <<<"$json")
        printf '{"id":"%s"}\n' "$id"
        ;;
      delete)
        id="${3:-}"; vault=""; prev=""
        for a in "$@"; do [[ "$prev" == "--vault" ]] && vault="$a"; prev="$a"; done
        rm -f "$state/${vault}__${id#id-}__"*
        ;;
      *) echo "fake op: unhandled item sub $sub" >&2; exit 1 ;;
    esac
    ;;
  *) echo "fake op: unhandled command $cmd" >&2; exit 1 ;;
esac
"""

FAKE_GH = r"""#!/usr/bin/env bash
set -uo pipefail
for a in "$@"; do
  case "$a" in val-*|SENTINEL_*) echo "LEAK: secret value on gh argv" >&2; exit 91 ;; esac
done
cat >/dev/null
printf 'GH %s\n' "$*" >> "$FAKE_LOG"
# Concurrency barrier: wait for the other channel's fake to start too.
if [[ -n "${FAKE_BARRIER_DIR:-}" ]]; then
  : > "$FAKE_BARRIER_DIR/gh"
  n=0; until [[ -e "$FAKE_BARRIER_DIR/curl" ]]; do n=$((n+1)); [[ $n -lt 100 ]] || { echo "barrier: curl never started" >&2; exit 1; }; sleep 0.1; done
fi
# Transient failure injection: the first N calls fail like a gh 5xx.
if [[ -n "${FAKE_GH_FAIL_TIMES:-}" ]]; then
  f="${FAKE_OP_STATE:?}/.gh-fails"; n="$(cat "$f" 2>/dev/null || echo 0)"
  if [[ "$n" -lt "$FAKE_GH_FAIL_TIMES" ]]; then echo $((n+1)) > "$f"; echo "HTTP 502: Bad Gateway (https://api.github.com/repos/x/actions/secrets/Y)" >&2; exit 1; fi
fi
"""

FAKE_CURL = r"""#!/usr/bin/env bash
set -uo pipefail
method="GET" url="" wout=""
prev=""
for a in "$@"; do
  case "$a" in val-*|SENTINEL_*) echo "LEAK: secret value on curl argv" >&2; exit 91 ;; esac
  [[ "$prev" == "--request" ]] && method="$a"
  [[ "$prev" == "--url" ]] && url="$a"
  [[ "$prev" == "--write-out" ]] && wout="$a"
  prev="$a"
done
cat >/dev/null
printf 'CURL %s %s\n' "$method" "$url" >> "$FAKE_LOG"
if [[ -n "${FAKE_BARRIER_DIR:-}" ]]; then
  : > "$FAKE_BARRIER_DIR/curl"
  n=0; until [[ -e "$FAKE_BARRIER_DIR/gh" ]]; do n=$((n+1)); [[ $n -lt 100 ]] || { echo "barrier: gh never started" >&2; exit 1; }; sleep 0.1; done
fi
if [[ -n "${FAKE_CURL_FAIL_URL_SUBSTR:-}" ]] && [[ "$url" == *"${FAKE_CURL_FAIL_URL_SUBSTR}"* ]]; then
  echo "fake curl: injected failure for $url" >&2
  exit 22
fi
# Transient injection (first N matching calls): a curl network rc, or an HTTP 5xx.
counted() { local f="${FAKE_OP_STATE:?}/.curl-$1" n; n="$(cat "$f" 2>/dev/null || echo 0)"; [[ "$n" -lt "$2" ]] || return 1; echo $((n+1)) > "$f"; }
if [[ -n "${FAKE_CURL_RC_URL_SUBSTR:-}" && "$url" == *"${FAKE_CURL_RC_URL_SUBSTR}"* ]] && counted rc "${FAKE_CURL_RC_TIMES:-1}"; then
  echo "fake curl: (56) Recv failure" >&2; exit "${FAKE_CURL_RC:-56}"
fi
status=200 body='{}'
if [[ -n "${FAKE_CURL_5XX_URL_SUBSTR:-}" && "$url" == *"${FAKE_CURL_5XX_URL_SUBSTR}"* ]] && counted 5xx "${FAKE_CURL_5XX_TIMES:-1}"; then
  status=503 body='{"message":"upstream unavailable"}'
elif [[ "$method" == "POST" && "$url" == *"/deploys"* ]]; then
  sid="${url##*/services/}"; sid="${sid%%/*}"; status=201 body="{\"id\":\"dep-$sid\"}"
elif [[ "$method" == "GET" && "$url" == *"/env-vars/"* && -n "${FAKE_CURL_ENV_DIR:-}" && -f "$FAKE_CURL_ENV_DIR/${url##*/}" ]]; then
  body="$(jq -Rs '{value: .}' < "$FAKE_CURL_ENV_DIR/${url##*/}")"
elif [[ "$method" == "GET" && "$url" == *"/deploys?limit=1"* ]]; then
  body='[{"deploy":{"id":"dep-old","status":"live"}}]'
elif [[ "$method" == "GET" && "$url" == *"/deploys/"* ]]; then
  body="{\"id\":\"${url##*/}\",\"status\":\"${FAKE_DEPLOY_STATUS:-live}\"}"
fi
printf '%s' "$body"
if [[ -n "$wout" ]]; then wout="${wout//\\n/$'\n'}"; printf '%s' "${wout//%\{http_code\}/$status}"; fi
"""

FAKE_SSH = r"""#!/usr/bin/env bash
set -uo pipefail
for a in "$@"; do
  case "$a" in *val-*|*SENTINEL_*) echo "LEAK: secret value on ssh argv" >&2; exit 91 ;; esac
done
printf 'SSH %s\n' "$*" >> "$FAKE_LOG"
last="${!#}"
case "$last" in
  "sudo -n true") exit 0 ;;
  *"sudo -n sh -c"*)
    # Batch mode: answer OK per path line, RESTARTED per unit (simulated box).
    while IFS=' ' read -r path sum b64; do
      if [[ "$path" == RESTART ]]; then for u in $sum $b64; do echo "RESTARTED $u"; done; continue; fi
      printf '%s' "$b64" | base64 -d > "${FAKE_SSH_DIR:?}/$(basename "$path")"
      echo "OK $path"
    done
    ;;
  *) cat >/dev/null; exit 1 ;;
esac
"""

FAKE_SECURITY = r"""#!/usr/bin/env bash
printf 'SECURITY %s\n' "$*" >> "$FAKE_LOG"
exit 1
"""

# uv double for the prefect writer's block-save entrypoint (logs argv only).
FAKE_UV = r"""#!/usr/bin/env bash
printf 'UV %s\n' "$*" >> "$FAKE_LOG"
exit "${FAKE_UV_EXIT:-0}"
"""

FAKE_SYNC = r"""#!/usr/bin/env bash
printf 'SYNC %s\n' "$*" >> "$FAKE_LOG"
exit "${FAKE_SYNC_EXIT:-0}"
"""


class SecretsSandbox:
    """Synthetic repo + fakes + scrubbed environment for engine tests."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.fakebin = self.root / "fakebin"
        self.state = self.root / "op-state"
        self.log_path = self.root / "fake.log"
        self.config_path = self.root / "project-tools.json"

        self.fakebin.mkdir()
        self.state.mkdir()
        self.repo.mkdir(parents=True)
        self._rotation: dict = {}
        self.write_manifest(MANIFEST)
        self.config_path.write_text(PROJECT_TOOLS, encoding="utf-8")

        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "remote", "add", "origin",
             "https://github.com/testorg/testrepo.git"],
            check=True,
        )

        for name, body in (
            ("op", FAKE_OP),
            ("gh", FAKE_GH),
            ("curl", FAKE_CURL),
            ("security", FAKE_SECURITY),
            ("ssh", FAKE_SSH),
            ("sync-secrets-fake", FAKE_SYNC),
            ("uv", FAKE_UV),
        ):
            path = self.fakebin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def close(self) -> None:
        self._tmp.cleanup()

    def write_manifest(self, content: str, rotation: dict | None = None,
                       hermes: dict | None = None) -> None:
        """Write the sandbox project secrets.yaml from TSV-style route rows.

        Rows convert field-for-field so malformed TSV becomes an equivalently
        malformed config the strict validator must reject (missing keys, bad
        kinds/transforms, duplicates)."""
        if rotation is not None:
            self._rotation = rotation
        keys = ("kind", "dest", "env", "ref", "transform")
        routes = []
        for line in content.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split("\t")
            row = {"repo": "repo"}
            row.update({k: v for k, v in zip(keys, fields)})
            routes.append(row)
        doc = {
            "project": "testproj",
            "repos": ["repo"],
            "health": {},
            "rotation": self._rotation,
            "routes": routes,
        }
        if hermes is not None:
            doc["hermes"] = hermes
        (self.repo / "secrets.yaml").write_text(
            yaml.safe_dump(doc, sort_keys=False), encoding="utf-8"
        )

    def env(self, *, sa_token: bool = True, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        for name in (
            *AGENT_MARKERS,
            "SECRETS_ALLOW_AGENT",
            "SENSITIVE_ACCESS_REASON",
            "OP_ACCESS_REASON",
            "OP_BIN",
            "OP_SERVICE_ACCOUNT_TOKEN",
            "RENDER_API_KEY",
            "SECRETS_SA_TOKEN_ENV",
            "SECRETS_SA_KEYCHAIN_ITEM",
            "SECRETS_RENDER_KEY_REF",
            "SECRETS_LIB",
            "_MANIFEST_FILE",
            "_SECRETS_CONFIG",
            "_CONFIG_ROWS",
            "_CONFIG_DOC",
            "_CONFIG_FILE",
            "_CONFIG_REGISTRY_FILE",
            "SECRET_ROTATION_CONFIG",
        ):
            env.pop(name, None)
        env.update(
            {
                "PATH": f"{self.fakebin}:{env.get('PATH', '')}",
                "OP_BIN": str(self.fakebin / "op"),
                "FAKE_LOG": str(self.log_path),
                "FAKE_OP_STATE": str(self.state),
                "PROJECT_TOOLS_CONFIG": str(self.config_path),
            }
        )
        if sa_token:
            env["TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN"] = SA_TOKEN_SENTINEL
        env.update(extra)
        return env

    def log_lines(self) -> list[str]:
        if not self.log_path.exists():
            return []
        return [line for line in self.log_path.read_text(encoding="utf-8").splitlines() if line]


def run(cmd: list[str], env: dict[str, str], *, stdin: str | None = None,
        cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        env=env,
        input=stdin,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=120,
    )
