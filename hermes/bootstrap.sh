#!/usr/bin/env bash
# Build a fresh Ubuntu Hermes host from reviewed code plus separately staged secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/hermes/versions.env"

HERMES_USER=hermes
HERMES_HOME=/home/hermes/.hermes
AGENT_DIR="$HERMES_HOME/hermes-agent"
INPUT_DIR=/etc/hermes-bootstrap
UV_DIR="$HERMES_HOME/bin"
UV="$UV_DIR/uv"
NODE_DIR="/opt/node-v${HERMES_NODE_VERSION}-linux-x64"
PINNED_AGENT_WORKFLOWS=https://github.com/simonszalai/agent-workflows.git
temporary=""
swap_temporary=""
agent_stage=""
node_stage=""
node_old=""

die() {
  echo "hermes bootstrap: $*" >&2
  exit 1
}

cleanup() {
  if [ -n "$node_old" ] && [ ! -e "$NODE_DIR" ]; then
    mv "$node_old" "$NODE_DIR"
    node_old=""
  fi
  [ -z "$swap_temporary" ] || rm -f -- "$swap_temporary"
  [ -z "$agent_stage" ] || rm -rf -- "$agent_stage"
  [ -z "$node_stage" ] || rm -rf -- "$node_stage"
  [ -z "$node_old" ] || rm -rf -- "$node_old"
  [ -z "$temporary" ] || rm -rf -- "$temporary"
}
trap cleanup EXIT

[ "$(id -u)" -eq 0 ] || die "run as root"
[ "$(uname -m)" = "$HERMES_ARCH" ] || die "expected architecture $HERMES_ARCH"
# shellcheck disable=SC1091
source /etc/os-release
[ "$ID" = "$HERMES_OS_ID" ] || die "expected $HERMES_OS_ID"
[ "$VERSION_ID" = "$HERMES_OS_VERSION" ] || die "expected OS version $HERMES_OS_VERSION"
[ -d /run/systemd/system ] || die "systemd is required"

# Bootstrap copies and executes privileged assets from this checkout, so fail
# before changing the host unless the entire tree is the current reviewed main.
[ "$(git -c core.fsmonitor=false -C "$ROOT" remote get-url origin)" = \
  "$PINNED_AGENT_WORKFLOWS" ] || die "agent-workflows origin is not pinned"
[ -z "$(git -c core.fsmonitor=false -C "$ROOT" status --porcelain --untracked-files=all)" ] ||
  die "agent-workflows checkout has uncommitted or untracked files"
BOOTSTRAP_REVISION="$(git -c core.fsmonitor=false -C "$ROOT" rev-parse HEAD)"
[[ "$BOOTSTRAP_REVISION" =~ ^[0-9a-f]{40}$ ]] || die "checkout revision is invalid"
REMOTE_MAIN_LINE="$(
  cd /
  env -i HOME=/nonexistent LANG=C.UTF-8 PATH=/usr/bin:/bin \
    GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 \
    timeout 180 git -c credential.helper= -c core.hooksPath=/dev/null \
      ls-remote --exit-code "$PINNED_AGENT_WORKFLOWS" refs/heads/main
)" || die "could not query pinned agent-workflows main"
read -r REMOTE_MAIN REMOTE_REF REMOTE_EXTRA <<< "$REMOTE_MAIN_LINE"
[[ "$REMOTE_MAIN" =~ ^[0-9a-f]{40}$ ]] &&
  [ "$REMOTE_REF" = refs/heads/main ] && [ -z "${REMOTE_EXTRA:-}" ] ||
  die "pinned remote returned an invalid main ref"
[ "$BOOTSTRAP_REVISION" = "$REMOTE_MAIN" ] ||
  die "bootstrap checkout must equal current pinned remote main"

check_secret() {
  local path="$1"
  [ -f "$path" ] && [ ! -L "$path" ] || die "missing regular secret input: $path"
  [ "$(stat -c '%u:%a' "$path")" = "0:400" ] ||
    die "secret input must be root-owned mode 0400: $path"
  [ -s "$path" ] || die "secret input is empty: $path"
}

check_secret "$INPUT_DIR/gateway.env"
check_secret "$INPUT_DIR/auth.json"
check_secret /etc/hermes-mcp/autodev-memory.token
check_secret /etc/hermes-conductor/conductor-api.token
check_secret /etc/hermes-schedules/slack.token
check_secret /etc/hermes-schedules/op.token
python3 "$ROOT/hermes/bin/validate-bootstrap-inputs" \
  "$INPUT_DIR/gateway.env" "$INPUT_DIR/auth.json" ||
  die "secret input structure is invalid"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  build-essential \
  ca-certificates \
  curl \
  ffmpeg \
  git \
  jq \
  nodejs \
  python3-dev \
  python3-venv \
  ripgrep \
  rsync \
  sudo \
  tar \
  ufw \
  xz-utils

if ! id "$HERMES_USER" >/dev/null 2>&1; then
  useradd --create-home --home-dir /home/hermes --shell /bin/bash "$HERMES_USER"
fi
[ "$(getent passwd "$HERMES_USER" | cut -d: -f6)" = /home/hermes ] ||
  die "the hermes account has an unexpected home directory"
install -d -o hermes -g hermes -m 0700 "$HERMES_HOME" "$UV_DIR"

expected_swap_bytes="$((HERMES_SWAP_MIB * 1024 * 1024))"
if [ -e /swapfile ]; then
  [ -f /swapfile ] && [ ! -L /swapfile ] || die "/swapfile must be a regular file"
  [ "$(stat -c '%u:%a:%s' /swapfile)" = "0:600:${expected_swap_bytes}" ] ||
    die "/swapfile does not match the rebuild contract"
fi
if ! swapon --show=NAME --noheadings | grep -Fxq /swapfile; then
  if [ ! -e /swapfile ]; then
    swap_temporary="/swapfile.bootstrap.$$"
    fallocate -l "${HERMES_SWAP_MIB}M" "$swap_temporary"
    chmod 0600 "$swap_temporary"
    mkswap "$swap_temporary" >/dev/null
    mv -T "$swap_temporary" /swapfile
    swap_temporary=""
  elif [ "$(blkid -o value -s TYPE /swapfile 2>/dev/null || true)" != swap ]; then
    # The exact root-owned path/size/mode above identifies an interrupted
    # bootstrap artifact. Repair its missing swap header on a rerun.
    mkswap /swapfile >/dev/null
  fi
  swapon /swapfile
fi
grep -Fqx '/swapfile none swap sw 0 0' /etc/fstab ||
  printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab

ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw logging low >/dev/null
ufw --force enable >/dev/null

temporary="$(mktemp -d)"

uv_archive="$temporary/uv.tar.gz"
curl --fail --location --silent --show-error \
  "https://github.com/astral-sh/uv/releases/download/${HERMES_UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
  --output "$uv_archive"
printf '%s  %s\n' "$HERMES_UV_SHA256" "$uv_archive" | sha256sum --check --status ||
  die "uv archive checksum mismatch"
tar -xzf "$uv_archive" -C "$temporary"
install -o hermes -g hermes -m 0755 \
  "$temporary/uv-x86_64-unknown-linux-gnu/uv" "$UV"
install -o hermes -g hermes -m 0755 \
  "$temporary/uv-x86_64-unknown-linux-gnu/uvx" "$UV_DIR/uvx"

node_archive="$temporary/node.tar.xz"
curl --fail --location --silent --show-error \
  "https://nodejs.org/dist/v${HERMES_NODE_VERSION}/node-v${HERMES_NODE_VERSION}-linux-x64.tar.xz" \
  --output "$node_archive"
printf '%s  %s\n' "$HERMES_NODE_SHA256" "$node_archive" | sha256sum --check --status ||
  die "Node archive checksum mismatch"
node_valid=false
if [ -d "$NODE_DIR" ] && [ ! -L "$NODE_DIR" ] &&
  [ "$(stat -c '%U:%G' "$NODE_DIR")" = root:root ] &&
  [ "$("$NODE_DIR/bin/node" --version 2>/dev/null || true)" = "v${HERMES_NODE_VERSION}" ] &&
  [ "$("$NODE_DIR/bin/npm" --version 2>/dev/null || true)" = "$HERMES_NPM_VERSION" ]; then
  node_valid=true
fi
if [ "$node_valid" = false ]; then
  [ ! -e "$NODE_DIR" ] || { [ -d "$NODE_DIR" ] && [ ! -L "$NODE_DIR" ]; } ||
    die "$NODE_DIR is not a replaceable managed directory"
  node_stage="/opt/.hermes-node-stage.$$"
  [ ! -e "$node_stage" ] || die "stale Node staging path exists: $node_stage"
  mkdir "$node_stage"
  tar -xJf "$node_archive" -C "$node_stage"
  extracted_node="$node_stage/node-v${HERMES_NODE_VERSION}-linux-x64"
  [ "$("$extracted_node/bin/node" --version)" = "v${HERMES_NODE_VERSION}" ] &&
    [ "$("$extracted_node/bin/npm" --version)" = "$HERMES_NPM_VERSION" ] ||
    die "staged Node distribution failed version validation"
  chown -R root:root "$extracted_node"
  chmod -R go-w "$extracted_node"
  if [ -e "$NODE_DIR" ]; then
    node_old="/opt/.hermes-node-replaced.$$"
    [ ! -e "$node_old" ] || die "stale Node replacement path exists: $node_old"
    mv "$NODE_DIR" "$node_old"
  fi
  mv "$extracted_node" "$NODE_DIR"
  rmdir "$node_stage"
  node_stage=""
fi
if [ -e "$HERMES_HOME/node" ] && [ ! -L "$HERMES_HOME/node" ]; then
  die "$HERMES_HOME/node exists and is not a managed symlink"
fi
ln -sfn "$NODE_DIR" "$HERMES_HOME/node"
chown -h hermes:hermes "$HERMES_HOME/node"

if [ ! -e "$AGENT_DIR" ]; then
  agent_stage="$HERMES_HOME/.hermes-agent-stage.$$"
  [ ! -e "$agent_stage" ] || die "stale Hermes agent staging path exists"
  install -d -o hermes -g hermes -m 0700 "$agent_stage"
  sudo -u hermes -H git \
    -c credential.helper= \
    -c core.hooksPath=/dev/null \
    clone --no-checkout "$HERMES_AGENT_REPOSITORY" "$agent_stage"
  sudo -u hermes -H git -C "$agent_stage" checkout --detach "$HERMES_AGENT_UPSTREAM_COMMIT"
  mv "$agent_stage" "$AGENT_DIR"
  agent_stage=""
fi
[ -d "$AGENT_DIR/.git" ] && [ ! -L "$AGENT_DIR" ] ||
  die "Hermes agent path is not a Git checkout"
[ "$(sudo -u hermes -H git -C "$AGENT_DIR" remote get-url origin)" = \
  "$HERMES_AGENT_REPOSITORY" ] || die "Hermes agent origin is not pinned upstream"
sudo -u hermes -H git -C "$AGENT_DIR" config user.name "Hermes local patch"
sudo -u hermes -H git -C "$AGENT_DIR" config user.email "hermes@localhost"
agent_revision="$(sudo -u hermes -H git -C "$AGENT_DIR" rev-parse HEAD)"
if [ -d "$AGENT_DIR/.git/rebase-apply" ]; then
  case "$agent_revision" in
    "$HERMES_AGENT_UPSTREAM_COMMIT"|"$HERMES_AGENT_PATCHED_COMMIT")
      sudo -u hermes -H git -C "$AGENT_DIR" am --abort ||
        die "could not recover an interrupted Hermes patch application"
      agent_revision="$(sudo -u hermes -H git -C "$AGENT_DIR" rev-parse HEAD)"
      ;;
    *) die "interrupted Hermes patch state is not based on a reviewed revision" ;;
  esac
fi
case "$agent_revision" in
  "$HERMES_AGENT_UPSTREAM_COMMIT")
    [ -z "$(sudo -u hermes -H git -C "$AGENT_DIR" status --porcelain)" ] ||
      die "Hermes agent upstream checkout has local changes"
    for patch in "$ROOT"/hermes/patches/*.patch; do
      [ -f "$patch" ] || continue
      sudo -u hermes -H git -C "$AGENT_DIR" \
        am --committer-date-is-author-date < "$patch"
    done
    ;;
  "$HERMES_AGENT_PATCHED_COMMIT")
    [ -z "$(sudo -u hermes -H git -C "$AGENT_DIR" status --porcelain)" ] ||
      die "Hermes agent patched checkout has local changes"
    ;;
  *) die "Hermes agent checkout is not at the reviewed revision" ;;
esac
[ "$(sudo -u hermes -H git -C "$AGENT_DIR" rev-parse HEAD)" = \
  "$HERMES_AGENT_PATCHED_COMMIT" ] || die "Hermes patch stack produced an unexpected commit"
printf '%s\n' git > "$AGENT_DIR/.install_method"
chown hermes:hermes "$AGENT_DIR/.install_method"

sudo -u hermes -H "$UV" python install "$HERMES_PYTHON_VERSION"
venv_valid=false
if [ -x "$AGENT_DIR/venv/bin/python" ] &&
  [ "$(sudo -u hermes -H "$AGENT_DIR/venv/bin/python" -c \
    'import platform; print(platform.python_version())' 2>/dev/null || true)" = \
    "$HERMES_PYTHON_VERSION" ]; then
  venv_valid=true
fi
if [ "$venv_valid" = false ]; then
  if [ -e "$AGENT_DIR/venv" ]; then
    [ -d "$AGENT_DIR/venv" ] && [ ! -L "$AGENT_DIR/venv" ] ||
      die "Hermes venv is not a replaceable managed directory"
    mv "$AGENT_DIR/venv" "$AGENT_DIR/.venv.replaced.$$"
  fi
  sudo -u hermes -H "$UV" venv \
    --python "$HERMES_PYTHON_VERSION" "$AGENT_DIR/venv"
fi
sudo -u hermes -H env \
  PATH="$UV_DIR:$NODE_DIR/bin:/usr/local/bin:/usr/bin:/bin" \
  VIRTUAL_ENV="$AGENT_DIR/venv" \
  "$UV" sync \
  --project "$AGENT_DIR" \
  --active \
  --locked \
  --extra all \
  --extra slack \
  --python "$AGENT_DIR/venv/bin/python"
find "$AGENT_DIR" -maxdepth 1 -type d -name '.venv.replaced.*' \
  -exec rm -rf -- {} +
sudo -u hermes -H env PATH="$NODE_DIR/bin:/usr/bin:/bin" \
  "$NODE_DIR/bin/npm" --prefix "$AGENT_DIR" ci --workspaces=false
WHATSAPP_BRIDGE="$AGENT_DIR/scripts/whatsapp-bridge"
[ -f "$WHATSAPP_BRIDGE/package-lock.json" ] ||
  die "WhatsApp bridge lockfile is missing from the pinned Hermes revision"
sudo -u hermes -H env PATH="$NODE_DIR/bin:/usr/bin:/bin" \
  "$NODE_DIR/bin/npm" --prefix "$WHATSAPP_BRIDGE" ci
sudo -u hermes -H python3 - "$WHATSAPP_BRIDGE" <<'PY'
import hashlib
import sys
from pathlib import Path

bridge = Path(sys.argv[1])
digest = hashlib.sha256((bridge / "package.json").read_bytes()).hexdigest()[:16]
(bridge / "node_modules" / ".hermes-pkg-hash").write_text(digest)
PY

install -o hermes -g hermes -m 0600 "$ROOT/hermes/config/config.yaml" \
  "$HERMES_HOME/config.yaml"
install -o hermes -g hermes -m 0600 "$ROOT/hermes/config/SOUL.md" \
  "$HERMES_HOME/SOUL.md"
install -o hermes -g hermes -m 0600 "$ROOT/hermes/config/slack-manifest.json" \
  "$HERMES_HOME/slack-manifest.json"
install -o hermes -g hermes -m 0600 "$INPUT_DIR/gateway.env" "$HERMES_HOME/.env"
install -o hermes -g hermes -m 0600 "$INPUT_DIR/auth.json" "$HERMES_HOME/auth.json"
install -d -o hermes -g hermes -m 0700 \
  "$HERMES_HOME/skills/ops/autodev-ops/references"
install -o hermes -g hermes -m 0644 \
  "$ROOT/hermes/config/skills/ops/autodev-ops/SKILL.md" \
  "$HERMES_HOME/skills/ops/autodev-ops/SKILL.md"
for reference in health-evidence.md slack-ops-channels.md; do
  install -o hermes -g hermes -m 0644 \
    "$ROOT/hermes/config/skills/ops/autodev-ops/references/$reference" \
    "$HERMES_HOME/skills/ops/autodev-ops/references/$reference"
done
install -o hermes -g hermes -m 0600 /dev/null "$HERMES_HOME/.no-bundled-skills"

"$ROOT/hermes/install.sh"
"$ROOT/hermes/verify.sh"

echo "hermes bootstrap: deterministic host structure and local services verified"
echo "hermes bootstrap: external Slack/xAI delivery still requires a live smoke test"
echo "hermes bootstrap: WhatsApp still requires QR pairing or a separately restored session"
