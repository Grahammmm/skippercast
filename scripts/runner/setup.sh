#!/usr/bin/env bash
# Set up one Linux box (Ubuntu 24.04, 4 vCPU / 8 GB is plenty) as SkipperCast's
# GitHub Actions runners, so the scheduled data jobs and CI cost no billed minutes
# once the repository is private. See docs/operations/runners.md.
#
#   sudo REPO=Grahammmm/skippercast RUNNER_TOKEN=<registration token> bash scripts/runner/setup.sh
#
# Registers RUNNERS (default 4) runner instances as systemd services with the
# labels `self-hosted,skippercast`, installs what the workflows expect on the
# host (git, curl, jq, gh, zip, build tools for tippecanoe, Chromium's shared
# libraries for Playwright) and leaves Python and Node to actions/setup-python
# and actions/setup-node, which cache toolchains under the runner's work folder.
#
# Re-run to add or upgrade instances; it is idempotent for an existing runner name.
set -euo pipefail

REPO=${REPO:?set REPO=owner/name}
RUNNER_TOKEN=${RUNNER_TOKEN:?set RUNNER_TOKEN to a fresh registration token (repo Settings → Actions → Runners → New self-hosted runner)}
RUNNERS=${RUNNERS:-4}
RUNNER_VERSION=${RUNNER_VERSION:-2.337.0}
RUNNER_SHA256=${RUNNER_SHA256:-70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613}   # linux-x64 2.337.0; set to "" for another arch or version
LABELS=${LABELS:-self-hosted,skippercast}
USER_NAME=runner
HOME_DIR=/opt/actions-runner

if [ "$(id -u)" -ne 0 ]; then echo "run as root (sudo)" >&2; exit 1; fi

echo "== host packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends \
  ca-certificates curl git jq zip unzip gnupg lsb-release \
  build-essential libsqlite3-dev zlib1g-dev \
  libicu-dev libkrb5-3 libssl3 libcurl4 \
  python3 python3-venv python3-pip
# GitHub CLI (used by the freshness monitor and the seafloor ledger PR step).
if ! command -v gh >/dev/null; then
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list
  apt-get update -q && apt-get install -y -q gh
fi
# Node 22 for `pnpm exec playwright install --with-deps` at setup time; the
# workflows still bring their own Node through actions/setup-node.
if ! command -v node >/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -q nodejs
fi
corepack enable || true

echo "== runner user"
id -u "$USER_NAME" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$HOME_DIR" --shell /bin/bash "$USER_NAME"
mkdir -p "$HOME_DIR" && chown "$USER_NAME:$USER_NAME" "$HOME_DIR"
# Playwright's Chromium needs sudo once for its shared libraries; the runner gets
# password-less sudo only for apt-get so `playwright install --with-deps` works.
cat > /etc/sudoers.d/actions-runner <<EOF
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/apt-get
EOF
chmod 0440 /etc/sudoers.d/actions-runner

echo "== Chromium shared libraries for the Playwright e2e job"
sudo -u "$USER_NAME" -H bash -c 'cd ~ && npx --yes playwright@1 install-deps chromium' || echo "playwright install-deps failed; the e2e job installs them itself with sudo apt-get"

echo "== runner binary $RUNNER_VERSION"
ARCH=$(uname -m); case "$ARCH" in x86_64) RARCH=x64;; aarch64) RARCH=arm64;; *) echo "unsupported arch $ARCH" >&2; exit 1;; esac
TARBALL="actions-runner-linux-$RARCH-$RUNNER_VERSION.tar.gz"
cd "$HOME_DIR"
if [ ! -f "$TARBALL" ]; then
  curl -fsSL -o "$TARBALL" "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/$TARBALL"
  if [ -n "$RUNNER_SHA256" ] && [ "$RARCH" = x64 ]; then echo "$RUNNER_SHA256  $TARBALL" | sha256sum -c -; fi
fi

for i in $(seq 1 "$RUNNERS"); do
  DIR="$HOME_DIR/r$i"; NAME="$(hostname -s)-$i"
  if [ -f "$DIR/.runner" ]; then echo "runner $NAME already configured"; continue; fi
  mkdir -p "$DIR" && tar xzf "$TARBALL" -C "$DIR" && chown -R "$USER_NAME:$USER_NAME" "$DIR"
  sudo -u "$USER_NAME" -H bash -c "cd '$DIR' && ./config.sh --unattended --url 'https://github.com/$REPO' --token '$RUNNER_TOKEN' --name '$NAME' --labels '$LABELS' --work _work --replace"
  (cd "$DIR" && ./svc.sh install "$USER_NAME" && ./svc.sh start)
  echo "runner $NAME registered and started"
done

echo "== done: $RUNNERS runners with labels $LABELS. Set repository variables DATA_RUNNER=skippercast and CI_RUNNER=skippercast to move the jobs here."
