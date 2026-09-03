#!/usr/bin/env bash
# Install or reconcile reviewed Hermes services on an already-bootstrapped host.
#
# Secret values are never accepted in argv or environment variables. Operators
# must stage the four root-only credential files before running this installer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PINNED_AGENT_WORKFLOWS=https://github.com/simonszalai/agent-workflows.git
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

GIT_REVISION="$(git -c core.fsmonitor=false -C "$ROOT" rev-parse HEAD)"
[[ "$GIT_REVISION" =~ ^[0-9a-f]{40}$ ]] || die "checkout HEAD is not a full Git SHA"
[ "$(git -c core.fsmonitor=false -C "$ROOT" remote get-url origin)" = \
  "$PINNED_AGENT_WORKFLOWS" ] ||
  die "agent-workflows origin is not the pinned public repository"
[ -z "$(git -c core.fsmonitor=false -C "$ROOT" status --porcelain --untracked-files=all)" ] ||
  die "checkout has uncommitted or untracked files; install only reviewed committed inputs"

# Query the pinned URL from / with all user/system Git configuration disabled,
# rather than trusting a possibly stale or rewritten local remote-tracking ref.
REMOTE_MAIN_LINE="$(
  cd /
  env -i \
    HOME=/nonexistent \
    LANG=C.UTF-8 \
    PATH=/usr/bin:/bin \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_TERMINAL_PROMPT=0 \
    timeout 180 git \
      -c credential.helper= \
      -c core.hooksPath=/dev/null \
      ls-remote --exit-code "$PINNED_AGENT_WORKFLOWS" refs/heads/main
)" || die "could not query pinned agent-workflows main"
read -r REMOTE_MAIN REMOTE_REF REMOTE_EXTRA <<< "$REMOTE_MAIN_LINE"
[[ "$REMOTE_MAIN" =~ ^[0-9a-f]{40}$ ]] &&
  [ "$REMOTE_REF" = refs/heads/main ] &&
  [ -z "${REMOTE_EXTRA:-}" ] || die "pinned remote returned an invalid main ref"
[ "$GIT_REVISION" = "$REMOTE_MAIN" ] ||
  die "checkout HEAD must equal current pinned remote main"

# All privileged copies and executions below come from an archive of the
# reviewed commit, never directly from the caller-owned working tree.
SOURCE_ROOT="$(mktemp -d)"
CONDUCTOR_NEW=""
CONDUCTOR_OLD=""
INSTALL_METHOD_TMP=""
cleanup() {
  if [ -n "$CONDUCTOR_OLD" ] && [ ! -e /opt/hermes-conductor/venv ]; then
    mv "$CONDUCTOR_OLD" /opt/hermes-conductor/venv
    CONDUCTOR_OLD=""
    systemctl start hermes-conductor.service 2>/dev/null || true
  fi
  rm -rf -- "$SOURCE_ROOT"
  [ -z "$CONDUCTOR_NEW" ] || rm -rf -- "$CONDUCTOR_NEW"
  [ -z "$CONDUCTOR_OLD" ] || rm -rf -- "$CONDUCTOR_OLD"
  [ -z "$INSTALL_METHOD_TMP" ] || rm -f -- "$INSTALL_METHOD_TMP"
}
trap cleanup EXIT
git -c core.fsmonitor=false -c core.hooksPath=/dev/null -C "$ROOT" \
  archive --format=tar "$GIT_REVISION" hermes mcp-proxies |
  tar -xf - -C "$SOURCE_ROOT"
chmod -R a+rX "$SOURCE_ROOT"

for drop_in in /etc/systemd/system/hermes-schedule@*.timer.d; do
  [ -e "$drop_in" ] || continue
  die "unsupported schedule timer drop-in must be reviewed and removed: $drop_in"
done

check_credential() {
  local path="$1"
  [ -f "$path" ] && [ ! -L "$path" ] || die "missing regular credential: $path"
  [ "$(stat -c '%u:%a' "$path")" = "0:400" ] ||
    die "credential must be root-owned mode 0400: $path"
  [ -s "$path" ] || die "credential is empty: $path"
}

check_credential /etc/hermes-mcp/autodev-memory.token
check_credential /etc/hermes-conductor/conductor-api.token
check_credential /etc/hermes-schedules/slack.token
check_credential /etc/hermes-schedules/op.token

id hermes-mcp >/dev/null 2>&1 ||
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin hermes-mcp
id hermes-conductor >/dev/null 2>&1 ||
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin hermes-conductor
id hermes-schedules >/dev/null 2>&1 ||
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin hermes-schedules
id hermes-schedule-builder >/dev/null 2>&1 ||
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin hermes-schedule-builder

install -d -o root -g root -m 0755 /opt/hermes-mcp /opt/hermes-conductor
install -o root -g root -m 0644 \
  "$SOURCE_ROOT/mcp-proxies/mcp-proxy.mjs" /opt/hermes-mcp/mcp-proxy.mjs
install -o root -g root -m 0644 \
  "$SOURCE_ROOT/mcp-proxies/waf-encode.mjs" /opt/hermes-mcp/waf-encode.mjs
install -o root -g root -m 0755 \
  "$SOURCE_ROOT/hermes/bin/run-autodev-memory" /opt/hermes-mcp/run-autodev-memory
install -o root -g root -m 0755 \
  "$SOURCE_ROOT/hermes/conductor/server.py" /opt/hermes-conductor/server.py

# Rebuild from an empty venv on every manual reconcile. In-place pip install
# leaves removed packages behind and cannot repair a wrong interpreter.
CONDUCTOR_NEW="$(mktemp -d /opt/hermes-conductor/.venv.new.XXXXXX)"
python3 -m venv "$CONDUCTOR_NEW"
"$CONDUCTOR_NEW/bin/pip" install \
  --isolated \
  --no-cache-dir \
  --require-hashes \
  --only-binary=:all: \
  --requirement "$SOURCE_ROOT/hermes/conductor/requirements.txt"
"$CONDUCTOR_NEW/bin/pip" check
chown -R root:root /opt/hermes-conductor
chmod -R go-w /opt/hermes-conductor
if [ -d /opt/hermes-conductor/venv ]; then
  CONDUCTOR_OLD="/opt/hermes-conductor/.venv.old.$$"
  systemctl stop hermes-conductor.service 2>/dev/null || true
  mv /opt/hermes-conductor/venv "$CONDUCTOR_OLD"
fi
if ! mv "$CONDUCTOR_NEW" /opt/hermes-conductor/venv; then
  [ -z "$CONDUCTOR_OLD" ] || mv "$CONDUCTOR_OLD" /opt/hermes-conductor/venv
  CONDUCTOR_OLD=""
  systemctl start hermes-conductor.service 2>/dev/null || true
  die "could not activate the rebuilt Conductor environment"
fi
CONDUCTOR_NEW=""
if [ -n "$CONDUCTOR_OLD" ]; then
  rm -rf -- "$CONDUCTOR_OLD"
  CONDUCTOR_OLD=""
fi

install -d -o root -g root -m 0755 /opt/hermes-schedules/bin
for executable in \
  hermes-schedule-release \
  hermes-schedule-alert \
  run-schedule-release \
  validate-schedule-release; do
  install -o root -g root -m 0755 \
    "$SOURCE_ROOT/hermes/bin/$executable" "/opt/hermes-schedules/bin/$executable"
done

install -d -o root -g root -m 0755 /opt/hermes-gateway-watchdog
install -o root -g root -m 0755 \
  "$SOURCE_ROOT/hermes/bin/gateway-watchdog" /opt/hermes-gateway-watchdog/gateway-watchdog
install -o root -g root -m 0644 \
  "$SOURCE_ROOT/hermes/systemd/hermes-gateway-watchdog.service" \
  /etc/systemd/system/hermes-gateway-watchdog.service
install -o root -g root -m 0644 \
  "$SOURCE_ROOT/hermes/systemd/hermes-gateway-watchdog.timer" \
  /etc/systemd/system/hermes-gateway-watchdog.timer

install -o root -g root -m 0644 \
  "$SOURCE_ROOT/hermes/systemd/hermes-autodev-mcp.service" \
  /etc/systemd/system/hermes-autodev-mcp.service
install -o root -g root -m 0644 \
  "$SOURCE_ROOT/hermes/systemd/hermes-conductor.service" \
  /etc/systemd/system/hermes-conductor.service
install -o root -g root -m 0644 \
  "$SOURCE_ROOT/hermes/systemd/hermes-gateway.service" \
  /etc/systemd/system/hermes-gateway.service
SCHEDULE_TIMERS=()
DESIRED_SCHEDULE_UNIT_TIMERS=()
for unit in "$SOURCE_ROOT"/hermes/systemd/hermes-schedule*; do
  name="$(basename "$unit")"
  install -o root -g root -m 0644 "$unit" "/etc/systemd/system/$name"
  case "$name" in
    *.timer) SCHEDULE_TIMERS+=("$name") ;;
  esac
  case "$name" in
    hermes-schedule@*.timer) DESIRED_SCHEDULE_UNIT_TIMERS+=("$name") ;;
  esac
done

# Schedule timer names are a repo-owned namespace. Disable and remove obsolete
# instances so deleting a schedule is deterministic rather than requiring
# undocumented manual cleanup. Drop-ins are rejected because they can silently
# change the reviewed calendar.
for installed in /etc/systemd/system/hermes-schedule@*.timer; do
  [ -e "$installed" ] || continue
  name="$(basename "$installed")"
  keep=false
  for desired in "${DESIRED_SCHEDULE_UNIT_TIMERS[@]}"; do
    [ "$name" = "$desired" ] && keep=true
  done
  if [ "$keep" = false ]; then
    systemctl disable --now "$name" 2>/dev/null || true
    rm -f -- "$installed"
  fi
done

# Build the entire schedule bundle before changing `current`. The release tool
# exports committed Git objects, validates the deployment contract against the
# reviewed timer files, installs hash-locked dependencies as the secretless builder,
# and switches one symlink. It never executes candidate runner code as root.
/opt/hermes-schedules/bin/hermes-schedule-release install-local \
  --repository "$ROOT" \
  --revision "$GIT_REVISION" \
  --timer-directory "$SOURCE_ROOT/hermes/systemd"

# Local hermes-agent patches (hermes/patches/*.patch) — behaviour fixes that
# upstream lacks. Applied idempotently as the hermes user; a patch that is
# already in the tree (by content) is skipped, a patch that no longer applies
# fails the install so the drift is reviewed instead of silently lost.
HERMES_AGENT_DIR="${HERMES_AGENT_DIR:-${HERMES_HOME}/hermes-agent}"
INSTALL_METHOD_TMP="$(mktemp "$HERMES_AGENT_DIR/.install_method.tmp.XXXXXX")"
printf '%s\n' git > "$INSTALL_METHOD_TMP"
chown hermes:hermes "$INSTALL_METHOD_TMP"
chmod 0644 "$INSTALL_METHOD_TMP"
mv -Tf -- "$INSTALL_METHOD_TMP" "$HERMES_AGENT_DIR/.install_method"
INSTALL_METHOD_TMP=""
for patch in "$SOURCE_ROOT"/hermes/patches/*.patch; do
  [ -f "$patch" ] || continue
  if sudo -u hermes -H git -C "$HERMES_AGENT_DIR" \
    apply --check --reverse < "$patch" >/dev/null 2>&1; then
    continue  # already applied
  fi
  sudo -u hermes -H git -C "$HERMES_AGENT_DIR" apply --check < "$patch" ||
    die "hermes-agent patch no longer applies: $patch"
  sudo -u hermes -H git -C "$HERMES_AGENT_DIR" apply < "$patch"
  echo "hermes install: applied $(basename "$patch")"
done

# The reviewed file is the complete non-secret runtime configuration. Reconcile
# it exactly so an existing host reaches the same state as a clean bootstrap.
install -o hermes -g hermes -m 0600 \
  "$SOURCE_ROOT/hermes/config/config.yaml" "$HERMES_CONFIG"

systemctl daemon-reload
systemctl enable --now \
  hermes-autodev-mcp.service \
  hermes-conductor.service \
  hermes-gateway.service
systemctl restart hermes-autodev-mcp.service hermes-conductor.service
systemctl restart hermes-gateway.service
# Timers are always enabled; runner.py skips entries with enabled:false, so
# activation is purely a reviewed schedules.yaml flip plus re-install.
systemctl enable --now "${SCHEDULE_TIMERS[@]}"
systemctl enable --now hermes-gateway-watchdog.timer

systemctl is-active --quiet hermes-autodev-mcp.service
systemctl is-active --quiet hermes-conductor.service
systemctl is-active --quiet hermes-gateway.service
for timer in "${SCHEDULE_TIMERS[@]}"; do
  systemctl is-active --quiet "$timer"
done
echo "hermes install: services active"
