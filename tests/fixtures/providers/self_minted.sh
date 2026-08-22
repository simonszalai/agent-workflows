# shellcheck shell=bash
# Test double for providers/self_minted.sh implementing the §1 provider
# contract: mints via the real vault layer, records a value-free finalize
# payload, and logs provider_finalize calls to $FAKE_LOG (exit FAKE_FINALIZE_EXIT).
# FAKE_ROTATE_RC=7 simulates leftovers (no mint); provider_reconcile then
# answers FAKE_RECONCILE_RC (0 -> finalize json {reconciled:true}).
provider_auto_ready() { return 0; }

provider_plan() { echo "  self_minted plan: mint + vault write (fixture)"; }

provider_reconcile() {
  printf 'RECONCILE %s\n' "$ROTATE_ID" >> "${FAKE_LOG:?}"
  case "${FAKE_RECONCILE_RC:-0}" in
    0) PROVIDER_FINALIZE_JSON='{"reconciled":true}'; echo "  fixture: leftovers reconciled" ;;
    *) echo "REFUSED: fixture reconcile playbook"; return "${FAKE_RECONCILE_RC}" ;;
  esac
}

provider_rotate() {
  local bytes new_value
  if [[ "${FAKE_ROTATE_RC:-0}" == "7" ]]; then echo "  fixture: leftovers found"; return 7; fi
  bytes="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.generate.bytes // 32')"
  new_value="$(openssl rand -hex "$bytes")"
  VAULT_VALUE="$new_value" vault_write_value "$ROTATE_REF" || { new_value=""; return 4; }
  new_value=""
  PROVIDER_FINALIZE_JSON="$(jq -n -c --arg id "$ROTATE_ID" '{predecessor: ("prev-" + $id)}')"
  echo "  minted new hex value for $ROTATE_REF ($bytes bytes)"
}

provider_verify() { # logged; FAKE_VERIFY_EXIT fails it
  printf 'VERIFY %s\n' "$ROTATE_ID" >> "${FAKE_LOG:?}"
  [[ "${FAKE_VERIFY_EXIT:-0}" == "0" ]]
}

provider_finalize() { # json
  printf 'FINALIZE %s %s\n' "$ROTATE_ID" "${1:-}" >> "${FAKE_LOG:?}"
  [[ "${FAKE_FINALIZE_EXIT:-0}" == "0" ]]
}

provider_playbook() { echo "self_minted fixture playbook for $ROTATE_REF"; }
