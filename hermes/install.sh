#!/usr/bin/env bash
# Install or reconcile the reviewed Hermes MCP services on a Linux host.
#
# Secret values are never accepted in argv or environment variables. Operators
# must stage the two root-only credential files before running this installer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-/home/hermes/.hermes}"
HERMES_CONFIG="${HERMES_CONFIG:-${HERMES_HOME}/config.yaml}"
HERMES_PYTHON="${HERMES_PYTHON:-${HERMES_HOME}/hermes-agent/venv/bin/python}"

die() {
  echo "hermes install: $*" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || die "run as root"
[ -f "$HERMES_CONFIG" ] || die "missing Hermes config: $HERMES_CONFIG"
[ -x "$HERMES_PYTHON" ] || die "missing Hermes Python: $HERMES_PYTHON"

check_credential() {
  local path="$1"
  [ -f "$path" ] && [ ! -L "$path" ] || die "missing regular credential: $path"
  [ "$(stat -c '%u:%a' "$path")" = "0:400" ] ||
    die "credential must be root-owned mode 0400: $path"
  [ -s "$path" ] || die "credential is empty: $path"
}

check_credential /etc/hermes-mcp/autodev-memory.token
check_credential /etc/hermes-conductor/conductor-api.token

id hermes-mcp >/dev/null 2>&1 ||
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin hermes-mcp
id hermes-conductor >/dev/null 2>&1 ||
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin hermes-conductor

install -d -o root -g root -m 0755 /opt/hermes-mcp /opt/hermes-conductor
install -o root -g root -m 0644 \
  "$ROOT/mcp-proxies/mcp-proxy.mjs" /opt/hermes-mcp/mcp-proxy.mjs
install -o root -g root -m 0644 \
  "$ROOT/mcp-proxies/waf-encode.mjs" /opt/hermes-mcp/waf-encode.mjs
install -o root -g root -m 0755 \
  "$ROOT/hermes/bin/run-autodev-memory" /opt/hermes-mcp/run-autodev-memory
install -o root -g root -m 0755 \
  "$ROOT/hermes/conductor/server.py" /opt/hermes-conductor/server.py

if [ ! -x /opt/hermes-conductor/venv/bin/python ]; then
  python3 -m venv /opt/hermes-conductor/venv
fi
/opt/hermes-conductor/venv/bin/pip install \
  --disable-pip-version-check \
  --no-cache-dir \
  --requirement "$ROOT/hermes/conductor/requirements.txt"
chown -R root:root /opt/hermes-conductor
chmod -R go-w /opt/hermes-conductor

install -o root -g root -m 0644 \
  "$ROOT/hermes/systemd/hermes-autodev-mcp.service" \
  /etc/systemd/system/hermes-autodev-mcp.service
install -o root -g root -m 0644 \
  "$ROOT/hermes/systemd/hermes-conductor.service" \
  /etc/systemd/system/hermes-conductor.service

"$HERMES_PYTHON" "$ROOT/hermes/configure.py" "$HERMES_CONFIG"
chown hermes:hermes "$HERMES_CONFIG"
chmod 0600 "$HERMES_CONFIG"

systemctl daemon-reload
systemctl enable --now hermes-autodev-mcp.service hermes-conductor.service
systemctl restart hermes-autodev-mcp.service hermes-conductor.service
systemctl restart hermes-gateway.service

systemctl is-active --quiet hermes-autodev-mcp.service
systemctl is-active --quiet hermes-conductor.service
systemctl is-active --quiet hermes-gateway.service
echo "hermes install: services active"
