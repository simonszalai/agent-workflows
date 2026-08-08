# shellcheck shell=bash
# providers/manual.sh — secrets whose new value is minted in an external UI
# (provider dashboards, coordinated multi-service credentials). `rotate-secret`
# prints the registry-supplied playbook and exits 3 WITHOUT changing anything;
# once the operator has the new value, `rotate-secret --complete` reads it from
# stdin once and performs the vault write + consumer fan-out.
#
# Sourced by bin/rotate-secret after read.sh + vault.sh. Interface:
#   provider_rotate     print the playbook; rc 3 (nothing changed)
#   provider_verify     nothing to verify automatically; rc 0
#   provider_playbook   the registry-supplied manual steps

provider_playbook() {
  local playbook
  playbook="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.playbook // ""')"
  if [[ -n "$playbook" ]]; then
    printf '%s\n' "$playbook"
  else
    echo "(rotation entry has no playbook text — add one to the project secrets.yaml)"
  fi
  cat <<EOF

When you have the new value, complete the rotation (vault write + fan-out):
  printf %s '<new-value>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
EOF
}

provider_rotate() {
  echo "MANUAL rotation required for $ROTATE_REF — nothing has been changed."
  echo
  provider_playbook
  return 3
}

provider_verify() {
  return 0
}
