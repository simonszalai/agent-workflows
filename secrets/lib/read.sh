# shellcheck shell=bash
# read.sh — 1Password access. The ONLY file in the secrets engine that talks to
# `op`.
#
# Sourced, not executed. Provides sensitivity-aware reads:
#   op://<VAULT>/...            -> project service-account token (silent, agent-safe)
#   op://<VAULT>-sensitive/...  -> the canonical agent-workflows bin/op shim
#                                  (owns account selection, reason enforcement,
#                                  auth preflight, and notification — projects
#                                  and this engine carry NO notification code)
#
# The vault SUFFIX encodes DATA-sensitivity, not environment. Staging vs prod is
# the ITEM NAME (STAGING_* / "<Product> staging") and/or which DEST a row targets.
#
# Project wiring (set by bin/sync-secrets from bin/project-context; no ambient
# fallback):
#   SECRETS_SA_TOKEN_ENV       name of the env var holding the project SA token
#   SECRETS_SA_KEYCHAIN_ITEM   macOS Keychain service name holding the SA token
#
# IRON RULE: secret VALUES never reach stdout, stderr, argv, or logs. Values
# flow `op read` -> pipe -> destination only. Callers MUST pipe, never capture
# into an argv or echo.

_SECRETS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Default op binary is the canonical agent-workflows shim co-located with this
# checkout — NOT a bare `op` from PATH (the shim owns sensitive-access gating).
OP_BIN="${OP_BIN:-$_SECRETS_LIB_DIR/../../bin/op}"

# --- tiny shared utilities --------------------------------------------------
need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing dependency: $1" >&2; exit 2; }; }

confirm() { # prompt -> rc 0 only on an explicit y/Y
  local reply
  read -r -p "$1 [y/N] " reply
  [[ "$reply" == "y" || "$reply" == "Y" ]]
}

op_desktop() {
  env -u OP_SERVICE_ACCOUNT_TOKEN OP_USE_CANONICAL_HUMAN_ACCOUNT=1 "$OP_BIN" "$@"
}

op_vault_mutation() { # vault, op args...
  local vault="$1"
  shift
  if [[ "$vault" == *-sensitive ]]; then
    # The canonical shim owns human-account selection, reason enforcement,
    # authentication preflight, and prompt-aware notification.
    "$OP_BIN" "$@"
  else
    # Plain-vault writes use the desktop account, not the read-only service
    # account, without being classified as sensitive access.
    op_desktop "$@"
  fi
}

# --- agent-shell guard ------------------------------------------------------
# Direct `op` from a sandboxed agent shell (Claude/Codex) triggers a 1Password
# prompt storm and hangs. This guard refuses *-sensitive reads (Touch ID legs)
# when an agent-only marker is present. Non-sensitive service-account reads
# stay silent and agent-safe, so they are NOT guarded. Escape hatch:
# SECRETS_ALLOW_AGENT=1.
guard_agent_shell() {
  if [[ -n "${CLAUDECODE:-}${CLAUDE_CODE_ENTRYPOINT:-}${CODEX_THREAD_ID:-}${CODEX_CI:-}${CODEX_WORKING_DIR:-}" \
        && -z "${SECRETS_ALLOW_AGENT:-}" ]]; then
    echo "ERROR: refusing a 1Password sensitive (Touch ID) read from an agent shell." >&2
    echo "Run from a normal terminal (or SECRETS_ALLOW_AGENT=1 if you know better)." >&2
    return 3
  fi
}

# Resolve a manifest REF: literal:<value> prints the committed non-secret value
# verbatim; op:// refs go through op_read_ref. NOTE: every caller MUST use
# resolve_ref (not op_read_ref) so literal rows work.
resolve_ref() {
  local ref="$1"
  case "$ref" in
    literal:*) printf %s "${ref#literal:}" ;;
    op://*) op_read_ref "$ref" ;;
    *) echo "ERROR: unknown ref form: $ref" >&2; return 2 ;;
  esac
}

sa_token() { # project service-account token from env or Keychain -> stdout (or rc 3)
  local tok=""
  if [[ -n "${SECRETS_SA_TOKEN_ENV:-}" ]]; then
    tok="${!SECRETS_SA_TOKEN_ENV:-}"
  fi
  if [[ -z "$tok" && -n "${SECRETS_SA_KEYCHAIN_ITEM:-}" ]]; then
    tok="$(security find-generic-password -s "$SECRETS_SA_KEYCHAIN_ITEM" -a simon -w 2>/dev/null || true)"
  fi
  if [[ -z "$tok" ]]; then
    echo "ERROR: no project service-account token (\$${SECRETS_SA_TOKEN_ENV:-<unset>} or Keychain ${SECRETS_SA_KEYCHAIN_ITEM:-<unset>}). Run via sync-secrets so project-context wires the project layer." >&2
    return 3
  fi
  printf %s "$tok"
}

# --- 1Password read with sensitivity-aware auth ----------------------------
# Output: the secret value on stdout — CALLER MUST PIPE IT, never capture into
# an argv or echo it.
op_read_ref() {
  local ref="$1"
  case "$ref" in
    op://*-sensitive/*)
      # Data-exposing secret -> the canonical shim (human account, Touch ID,
      # reason gate, notification). Refuse from agent shells.
      guard_agent_shell || return $?
      "$OP_BIN" read --no-newline "$ref"
      ;;
    op://*/*/*)
      # Non-sensitive -> the project service-account token, from env or the
      # Keychain. ONE path, no ambient-op fallback (that silently read from
      # whatever account op defaulted to and produced wrong-account errors).
      local tok
      tok="$(sa_token)" || return $?
      OP_SERVICE_ACCOUNT_TOKEN="$tok" "$OP_BIN" read --no-newline "$ref"
      ;;
    *)
      echo "ERROR: not an op:// reference: $ref" >&2
      return 2
      ;;
  esac
}
