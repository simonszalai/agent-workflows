# shellcheck shell=bash
# Test double for providers/manual.sh: never mints; accepts --complete.
PROVIDER_ACCEPTS_COMPLETE=1

provider_auto_ready() { return 1; }

provider_playbook() {
  printf '%s\n' "$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.playbook // "(no playbook)"')"
  echo "When you have the new value: printf %s '<new-value>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete"
}

provider_rotate() {
  echo "MANUAL rotation required for $ROTATE_REF — nothing has been changed."
  provider_playbook
  return 3
}

provider_verify() { return 0; }

provider_finalize() { # json — nothing to retire for an externally minted value
  printf 'FINALIZE %s %s\n' "$ROTATE_ID" "${1:-}" >> "${FAKE_LOG:?}"
  return 0
}
