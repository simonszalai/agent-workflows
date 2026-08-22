# shellcheck shell=bash
# Test double for providers/postgres.sh (classification + plan only; rotate-project
# tests drive a fake rotate-secret, never this rotate path).
provider_auto_ready() { return 0; }
provider_plan() { echo "  postgres plan (fixture)"; }
provider_rotate() { echo "fixture postgres rotate EXTRA=${ROTATE_EXTRA_CONSUMER_DESTS:-}"; }
provider_verify() { return 0; }
provider_finalize() { printf 'FINALIZE %s %s\n' "$ROTATE_ID" "${1:-}" >> "${FAKE_LOG:?}"; }
provider_playbook() { echo "postgres fixture playbook"; }
