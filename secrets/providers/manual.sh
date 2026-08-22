# shellcheck shell=bash
# providers/manual.sh — secrets whose new value is minted in an external UI
# (provider dashboards, coordinated multi-service credentials, the xAI
# console). `rotate-secret` prints the registry-supplied playbook and exits 3
# WITHOUT changing anything; once the operator has the new value,
# `rotate-secret --complete` reads it from stdin once and performs the vault
# write + consumer fan-out (PROVIDER_ACCEPTS_COMPLETE=1).
# shellcheck source=../lib/provider-common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/provider-common.sh"

PROVIDER_ACCEPTS_COMPLETE=1

provider_auto_ready() { return 1; }

provider_playbook() {
  local playbook
  playbook="$(entry_field '.playbook')"
  if [[ -n "$playbook" ]]; then
    printf '%s\n' "$playbook"
  else
    echo "(rotation entry has no playbook text — add one to the project secrets.yaml)"
  fi
  cat <<EOF

When you have the new value, complete the rotation (vault write + fan-out):
  printf %s '<new-value>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
Retire the old credential in the provider UI only after every consumer
redeployed and verified.
EOF
}

provider_rotate() {
  echo "MANUAL rotation required for $ROTATE_REF — nothing has been changed."
  echo
  provider_playbook
  return 3
}

provider_verify() {
  local v
  verify_command_configured || return 0
  v="$(op_vault_read "$ROTATE_REF")" || return 1
  run_verify_command "$v"
}
