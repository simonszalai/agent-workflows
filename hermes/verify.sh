#!/usr/bin/env bash
# Verify the reproducible Hermes host contract without reading secret values.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/hermes/versions.env"
HERMES_HOME=/home/hermes/.hermes
AGENT_DIR="$HERMES_HOME/hermes-agent"

die() {
  echo "hermes verify: $*" >&2
  exit 1
}

check_secret() {
  local path="$1"
  [ -f "$path" ] && [ ! -L "$path" ] || die "missing regular credential: $path"
  [ "$(stat -c '%u:%a' "$path")" = "0:400" ] ||
    die "credential mode or owner is wrong: $path"
  [ -s "$path" ] || die "credential is empty: $path"
}

check_same() {
  local source="$1"
  local destination="$2"
  cmp --silent "$source" "$destination" || die "managed file drifted: $destination"
}

[ "$(id -u)" -eq 0 ] || die "run as root"
[ "$(uname -m)" = "$HERMES_ARCH" ] || die "host architecture drifted"
# shellcheck disable=SC1091
source /etc/os-release
[ "$ID" = "$HERMES_OS_ID" ] && [ "$VERSION_ID" = "$HERMES_OS_VERSION" ] ||
  die "host OS drifted"
[ "$(stat -c '%u:%a:%s' /swapfile)" = \
  "0:600:$((HERMES_SWAP_MIB * 1024 * 1024))" ] || die "swap file drifted"
swapon --show=NAME --noheadings | grep -Fxq /swapfile || die "swap is not active"
ufw status | grep -Fq 'Status: active' || die "firewall is not active"
[ "$(sudo -u hermes -H git -C "$AGENT_DIR" rev-parse HEAD)" = \
  "$HERMES_AGENT_PATCHED_COMMIT" ] || die "Hermes agent revision drifted"
[ -z "$(sudo -u hermes -H git -C "$AGENT_DIR" status --porcelain)" ] ||
  die "Hermes agent checkout is dirty"
[ "$(sudo -u hermes -H "$HERMES_HOME/bin/uv" --version | awk '{print $2}')" = \
  "$HERMES_UV_VERSION" ] || die "uv version drifted"
[ "$(sudo -u hermes -H "$AGENT_DIR/venv/bin/python" -c \
  'import platform; print(platform.python_version())')" = "$HERMES_PYTHON_VERSION" ] ||
  die "Hermes Python version drifted"
[ "$(/home/hermes/.hermes/node/bin/node --version)" = "v${HERMES_NODE_VERSION}" ] ||
  die "Node version drifted"
[ "$(/home/hermes/.hermes/node/bin/npm --version)" = "$HERMES_NPM_VERSION" ] ||
  die "npm version drifted"
[ "$(/usr/bin/node --version)" = "v${HERMES_SYSTEM_NODE_VERSION}" ] ||
  die "system Node version drifted"
sudo -u hermes -H "$AGENT_DIR/venv/bin/python" -c \
  'import aiohttp, slack_bolt, slack_sdk' || die "locked Slack dependencies are missing"
hermes_version="$(
  sudo -u hermes -H "$AGENT_DIR/venv/bin/python" -m hermes_cli.main --version
)"
grep -Fq "Hermes Agent v${HERMES_AGENT_VERSION} " <<< "$hermes_version" ||
  die "Hermes version drifted"

check_same "$ROOT/hermes/config/config.yaml" "$HERMES_HOME/config.yaml"
check_same "$ROOT/hermes/config/SOUL.md" "$HERMES_HOME/SOUL.md"
check_same "$ROOT/hermes/config/slack-manifest.json" "$HERMES_HOME/slack-manifest.json"
[ -f "$HERMES_HOME/.no-bundled-skills" ] && [ ! -s "$HERMES_HOME/.no-bundled-skills" ] ||
  die ".no-bundled-skills marker drifted"
check_same "$ROOT/hermes/config/skills/ops/autodev-ops/SKILL.md" \
  "$HERMES_HOME/skills/ops/autodev-ops/SKILL.md"
for reference in health-evidence.md slack-ops-channels.md; do
  check_same "$ROOT/hermes/config/skills/ops/autodev-ops/references/$reference" \
    "$HERMES_HOME/skills/ops/autodev-ops/references/$reference"
done
check_same "$ROOT/mcp-proxies/mcp-proxy.mjs" /opt/hermes-mcp/mcp-proxy.mjs
check_same "$ROOT/mcp-proxies/waf-encode.mjs" /opt/hermes-mcp/waf-encode.mjs
check_same "$ROOT/hermes/bin/run-autodev-memory" /opt/hermes-mcp/run-autodev-memory
check_same "$ROOT/hermes/conductor/server.py" /opt/hermes-conductor/server.py
check_same "$ROOT/hermes/bin/gateway-watchdog" \
  /opt/hermes-gateway-watchdog/gateway-watchdog
for executable in \
  hermes-schedule-release \
  hermes-schedule-alert \
  run-schedule-release \
  validate-schedule-release; do
  check_same "$ROOT/hermes/bin/$executable" "/opt/hermes-schedules/bin/$executable"
done
id hermes-schedule-builder >/dev/null 2>&1 ||
  die "schedule builder account is missing"
for unit in "$ROOT"/hermes/systemd/*; do
  check_same "$unit" "/etc/systemd/system/$(basename "$unit")"
done

check_secret /etc/hermes-mcp/autodev-memory.token
check_secret /etc/hermes-conductor/conductor-api.token
check_secret /etc/hermes-schedules/slack.token
check_secret /etc/hermes-schedules/op.token
[ "$(stat -c '%U:%G:%a' "$HERMES_HOME/.env")" = "hermes:hermes:600" ] ||
  die "gateway environment permissions drifted"
[ "$(stat -c '%U:%G:%a' "$HERMES_HOME/auth.json")" = "hermes:hermes:600" ] ||
  die "provider authentication permissions drifted"
python3 "$ROOT/hermes/bin/validate-bootstrap-inputs" \
  "$HERMES_HOME/.env" "$HERMES_HOME/auth.json" >/dev/null ||
  die "gateway or provider input structure drifted"
sudo -u hermes -H python3 - "$AGENT_DIR/scripts/whatsapp-bridge" <<'PY' ||
import hashlib
import sys
from pathlib import Path

bridge = Path(sys.argv[1])
expected = hashlib.sha256((bridge / "package.json").read_bytes()).hexdigest()[:16]
actual = (bridge / "node_modules" / ".hermes-pkg-hash").read_text().strip()
raise SystemExit(0 if expected == actual and (bridge / "package-lock.json").is_file() else 1)
PY
  die "WhatsApp bridge dependencies are missing or stale"

for service in hermes-autodev-mcp hermes-conductor hermes-gateway; do
  systemctl is-active --quiet "$service" || die "$service is not active"
  systemctl is-enabled --quiet "$service" || die "$service is not enabled"
done
for timer_path in "$ROOT"/hermes/systemd/*.timer; do
  timer="$(basename "$timer_path")"
  systemctl is-active --quiet "$timer" || die "$timer is not active"
  systemctl is-enabled --quiet "$timer" || die "$timer is not enabled"
done

/opt/hermes-schedules/bin/hermes-schedule-release status >/dev/null
current_release="$(readlink -e /opt/hermes-schedules/current)"
/opt/hermes-schedules/bin/validate-schedule-release \
  "$current_release" /etc/systemd/system >/dev/null
ss -ltn | grep -Eq '127[.]0[.]0[.]1:8792\b' || die "autodev-memory MCP is not listening"
ss -ltn | grep -Eq '127[.]0[.]0[.]1:8794\b' || die "Conductor MCP is not listening"

echo "hermes verify: host contract is healthy"
