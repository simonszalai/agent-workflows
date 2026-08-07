# shellcheck shell=bash
# providers/xai.sh — xAI API keys. MANUAL by design (exit 3), nothing changed.
#
# Evidence check (2026-08-07, slice 4a): the ts repos consume
# XAI_MANAGEMENT_API_KEY exclusively through xai-sdk gRPC channels for the
# collections API (ts-prefect src/blocks/xai.py `_management_channel`); no REST
# key-management endpoint shape is confirmed anywhere in our code. Per house
# rules this provider does NOT invent endpoints: rotation goes through the xAI
# console and completes with `rotate-secret --complete`.
#
# When xAI's key-management API shape is confirmed, extend this provider with
# registry-driven config (endpoint + management key ref) before any live call.

provider_playbook() {
  cat <<EOF
MANUAL: xAI exposes no key-rotation API shape we have confirmed (the management
key is only used for the xai-sdk collections gRPC channel). Rotate via console:
  1. console.x.ai -> API keys: create a new key with the same scopes/ACLs as
     the current one (check the old key's ACLs before creating).
  2. printf %s '<new-key>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
     (writes the vault item in place and fans out sync-secrets to consumers).
  3. For ts prefect-block consumers, additionally run:
     sync-secrets --repo /Users/simon/dev/ts-prefect --channel prefect
  4. Verify consumers work with the new key, THEN delete the old key in the
     console — never before.
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
