#!/usr/bin/env bash
# Install, update or roll back the SkipperCast fleet AIS listener (design.md section 10, CF-42).
#
#   AISSTREAM_API_KEY=<key> bash scripts/fleet/install_listener.sh --region CA   # deploy this checkout's HEAD
#   bash scripts/fleet/install_listener.sh --region CA --rollback [<sha>]        # back to a kept revision
#
# Runs as the data runner's user; .github/workflows/fleet-ais-listener.yml calls it on
# `vars.DATA_RUNNER`. Install:
#
#   1. copies the revision (git archive of HEAD: pyproject.toml, src, regions, catalog,
#      schemas, jurisdictions, scripts/fleet) to ~/.local/share/skippercast/app/<sha>, builds
#      its own virtualenv there with the `fleet` extra's packages, and checks that the region's
#      fleet.json loads with that interpreter;
#   2. repoints app/current at it (app/previous keeps the revision it replaced);
#   3. writes ~/.config/skippercast/fleet-ais.env with mode 0600 (AISSTREAM_API_KEY,
#      SKIPPERCAST_FLEET_VAR, SKIPPERCAST_GIT_SHA);
#   4. installs the user unit skippercast-fleet-ais@.service, enables and restarts
#      skippercast-fleet-ais@<REGION>;
#   5. fails unless <FLEET_VAR>/<REGION>/ais/heartbeat.json shows this revision receiving
#      messages within HEARTBEAT_TIMEOUT seconds (90);
#   6. keeps the newest KEEP_REVISIONS revisions (3), always including current and previous.
#
# --rollback repoints app/current at a kept revision (default: app/previous), rewrites only
# SKIPPERCAST_GIT_SHA in the env file, reinstalls that revision's unit, restarts and runs the
# same heartbeat check. Runbook: docs/operations/runbooks/fleet-ais-down.md.
#
# The aisstream key is never traced or printed: no xtrace, and the shell only tests that the
# variable is non-empty; Python reads it from the environment and writes the env file.
# Owner, once per box: `sudo loginctl enable-linger <runner user>` so the user's systemd
# manager runs without a login session.
set +x
set -euo pipefail

die() { echo "install_listener: $*" >&2; exit 1; }
note() { echo "== $*"; }

REGION=""
MODE=install
ROLLBACK_SHA=""
while [ $# -gt 0 ]; do
  case "$1" in
    --region) [ $# -ge 2 ] || die "--region needs a value"; REGION=$2; shift 2 ;;
    --region=*) REGION=${1#--region=}; shift ;;
    --rollback)
      MODE=rollback; shift
      if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then ROLLBACK_SHA=$1; shift; fi ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done

[[ "$REGION" =~ ^[A-Z]{2}$ ]] || die "--region must be a two-letter fleet region id such as CA"
[ -z "$ROLLBACK_SHA" ] || [[ "$ROLLBACK_SHA" =~ ^[0-9a-f]{40}$ ]] || die "--rollback takes a full 40-character commit sha"

PYTHON=${PYTHON:-python3}
HEARTBEAT_TIMEOUT=${HEARTBEAT_TIMEOUT:-90}
HEARTBEAT_POLL=${HEARTBEAT_POLL:-5}
KEEP_REVISIONS=${KEEP_REVISIONS:-3}
[ "${HOME:-}" ] || die "HOME is not set"
# These paths match the unit's %h paths; they are not configurable on their own.
APP="$HOME/.local/share/skippercast/app"
CONFIG_DIR="$HOME/.config/skippercast"
ENV_FILE="$CONFIG_DIR/fleet-ais.env"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_TEMPLATE=skippercast-fleet-ais@.service
UNIT="skippercast-fleet-ais@$REGION.service"
FLEET_VAR=${SKIPPERCAST_FLEET_VAR:-$HOME/.local/share/skippercast/fleet}
if [ "$MODE" = rollback ] && [ -f "$ENV_FILE" ]; then
  # A rollback keeps the store the unit already uses, whatever the caller's shell says.
  KEPT_VAR=$(sed -n 's/^SKIPPERCAST_FLEET_VAR=//p' "$ENV_FILE" | tail -n 1)
  FLEET_VAR=${KEPT_VAR:-$FLEET_VAR}
fi
HEARTBEAT="$FLEET_VAR/$REGION/ais/heartbeat.json"
ARCHIVE_PATHS=(pyproject.toml src regions catalog schemas jurisdictions scripts/fleet)

# systemctl --user from a runner job: the job has no login session, so point it at the
# lingering user manager's runtime directory.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

preflight() {
  "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null \
    || die "$PYTHON is missing or older than 3.11 (set PYTHON=/path/to/python3)"
  systemctl --user show-environment >/dev/null 2>&1 \
    || die "no user systemd manager for $(id -un) (owner step: sudo loginctl enable-linger $(id -un))"
}

# check_key: fail early, without showing it, on a key the env file could not hold as written.
check_key() {
  "$PYTHON" - <<'PY'
import os
import re
import sys

if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{8,512}", os.environ.get("AISSTREAM_API_KEY", "").strip()):
    sys.exit("install_listener: AISSTREAM_API_KEY has unexpected characters (value not shown)")
PY
}

# write_env <sha>: the env file, 0600, written atomically. The key comes from the
# environment on install, or from the existing file on rollback; it is never printed.
write_env() {
  mkdir -p "$CONFIG_DIR"
  chmod 0700 "$CONFIG_DIR"
  "$PYTHON" - "$ENV_FILE" "$1" "$FLEET_VAR" "$MODE" <<'PY'
import os
import re
import sys

path, sha, fleet_var, mode = sys.argv[1:5]
values = {}
if mode == "rollback":
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                name, sep, value = line.rstrip("\n").partition("=")
                if sep and not name.startswith("#"):
                    values[name.strip()] = value.strip()
    except FileNotFoundError:
        sys.exit("install_listener: no env file to roll back with; run a full install")
    key = values.get("AISSTREAM_API_KEY", "")
else:
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
if not key:
    sys.exit("install_listener: no aisstream key (owner step: add the AISSTREAM_API_KEY secret)")
if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{8,512}", key):
    sys.exit("install_listener: AISSTREAM_API_KEY has unexpected characters (value not shown)")
if not re.fullmatch(r"/[^\s\"'\\$`#]*", fleet_var):
    sys.exit("install_listener: SKIPPERCAST_FLEET_VAR must be an absolute path without spaces or quotes")
values.update(AISSTREAM_API_KEY=key, SKIPPERCAST_FLEET_VAR=fleet_var, SKIPPERCAST_GIT_SHA=sha)
body = "".join(f"{name}={values[name]}\n" for name in ("AISSTREAM_API_KEY", "SKIPPERCAST_FLEET_VAR", "SKIPPERCAST_GIT_SHA"))
tmp = f"{path}.tmp-{os.getpid()}"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
except BaseException:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise
PY
}

# build_revision <source checkout> <sha>: app/<sha> with its virtualenv; reused when complete.
build_revision() {
  local source=$1 sha=$2 dir="$APP/$2" present=()
  if [ -f "$dir/.complete" ]; then
    note "revision $sha already built"
    return 0
  fi
  rm -rf "$dir"
  mkdir -p "$dir"
  mapfile -t present < <(git -C "$source" ls-tree --name-only "$sha" -- "${ARCHIVE_PATHS[@]}")
  for required in pyproject.toml src scripts/fleet; do
    printf '%s\n' "${present[@]}" | grep -qx "$required" || die "revision $sha has no $required"
  done
  note "copying $sha to $dir"
  git -C "$source" archive --format=tar "$sha" -- "${present[@]}" | tar -x -C "$dir"
  "$PYTHON" - "$dir/pyproject.toml" > "$dir/.fleet-requirements.txt" <<'PY'
import re
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    project = tomllib.load(handle)["project"]
extras = project.get("optional-dependencies", {})
requirements, seen = list(project.get("dependencies", [])), set()


def add(extra):
    if extra in seen:
        return
    seen.add(extra)
    for requirement in extras.get(extra, []):
        own = re.fullmatch(r"skippercast\[([\w,-]+)\]", requirement.replace(" ", ""))
        if own:
            for name in own.group(1).split(","):
                add(name)
        else:
            requirements.append(requirement)


add("fleet")
print("\n".join(dict.fromkeys(requirements)))
PY
  note "building the virtualenv ($(wc -w < "$dir/.fleet-requirements.txt" | tr -d ' ') packages from the fleet extra)"
  "$PYTHON" -m venv --without-pip "$dir/.venv"
  if [ -s "$dir/.fleet-requirements.txt" ] && grep -q '[^[:space:]]' "$dir/.fleet-requirements.txt"; then
    "$dir/.venv/bin/python" -m ensurepip --default-pip >/dev/null
    "$dir/.venv/bin/python" -m pip install --quiet --disable-pip-version-check --no-input \
      --require-virtualenv -r "$dir/.fleet-requirements.txt"
  fi
  note "checking regions/$REGION/fleet.json loads with this revision"
  PYTHONPATH="$dir/src" "$dir/.venv/bin/python" -c \
    'import sys; from skippercast.fleet.config import load_region; load_region(sys.argv[1])' "$REGION" \
    || die "regions/$REGION/fleet.json does not load at $sha"
  touch "$dir/.complete"
}

# point <link name> <sha>: atomic symlink swap inside app/.
point() {
  ln -sfn "$2" "$APP/.$1.new"
  mv -Tf "$APP/.$1.new" "$APP/$1"
}

current_sha() { basename "$(readlink "$APP/current" 2>/dev/null || true)"; }

activate() {
  local sha=$1 old
  old=$(current_sha)
  write_env "$sha"   # first: if it fails, nothing has moved
  point current "$sha"
  if [ -n "$old" ] && [ "$old" != "$sha" ] && [ -d "$APP/$old" ]; then point previous "$old"; fi
  mkdir -p "$UNIT_DIR" "$FLEET_VAR"
  chmod 0700 "$FLEET_VAR"
  install -m 0644 "$APP/$sha/scripts/fleet/$UNIT_TEMPLATE" "$UNIT_DIR/$UNIT_TEMPLATE"
  systemctl --user daemon-reload
  systemctl --user enable "$UNIT" >/dev/null
  note "restarting $UNIT at $sha"
  systemctl --user restart "$UNIT"
}

# heartbeat_ok <sha> <since epoch>: 0 once this revision's heartbeat shows a message.
heartbeat_ok() {
  "$PYTHON" - "$HEARTBEAT" "$1" "$2" "${3:-}" <<'PY'
from datetime import datetime
import json
import sys

path, sha, since, verbose = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4] == "verbose"


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else None


try:
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    started, last = stamp(doc.get("started_at")), stamp(doc.get("last_message_at"))
except (OSError, ValueError, AttributeError):
    if verbose:
        print(f"no readable heartbeat at {path}")
    sys.exit(1)
fresh = doc.get("git_sha") == sha and started is not None and started >= since - 5
ok = fresh and last is not None and last >= started
if ok or verbose:
    fields = ("git_sha", "started_at", "written_at", "connected", "last_message_at", "messages_per_min",
              "watched_messages_per_min", "vessels", "reconnects", "last_error", "queue_depth", "watch_size")
    print("heartbeat: " + ", ".join(f"{name}={doc.get(name)!r}" for name in fields))
    if not fresh:
        print("heartbeat is not from the process this install started (old git_sha or started_at)")
sys.exit(0 if ok else 1)
PY
}

wait_for_heartbeat() {
  local sha=$1 since=$2 deadline=$(( $(date +%s) + HEARTBEAT_TIMEOUT ))
  note "waiting up to ${HEARTBEAT_TIMEOUT}s for $HEARTBEAT to show messages"
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if heartbeat_ok "$sha" "$since"; then return 0; fi
    sleep "$HEARTBEAT_POLL"
  done
  heartbeat_ok "$sha" "$since" verbose && return 0
  echo "::error title=AIS listener has no messages::$UNIT shows no aisstream messages ${HEARTBEAT_TIMEOUT}s after the restart; see docs/operations/runbooks/fleet-ais-down.md" >&2
  systemctl --user --no-pager --lines=0 status "$UNIT" >&2 || true
  echo "-- journalctl --user -u $UNIT (last 60 lines; empty for a system user: see the runbook)" >&2
  journalctl --user -u "$UNIT" -n 60 --no-pager >&2 || true
  echo "The new revision keeps running and retrying. Roll back with:" >&2
  echo "  bash $APP/current/scripts/fleet/install_listener.sh --region $REGION --rollback" >&2
  return 1
}

prune() {
  local keep_current keep_previous kept=0 name
  keep_current=$(current_sha)
  keep_previous=$(basename "$(readlink "$APP/previous" 2>/dev/null || true)")
  # Newest first; current and previous always stay.
  while IFS= read -r name; do
    [[ "$name" =~ ^[0-9a-f]{40}$ ]] || continue
    if [ "$name" = "$keep_current" ] || [ "$name" = "$keep_previous" ]; then continue; fi
    kept=$((kept + 1))
    if [ "$kept" -gt $(( KEEP_REVISIONS - 2 )) ]; then
      note "removing old revision $name"
      rm -rf "${APP:?}/$name"
    fi
  done < <(ls -1t "$APP")
}

preflight
if [ "$MODE" = install ]; then
  [ -n "${AISSTREAM_API_KEY:-}" ] || die "AISSTREAM_API_KEY is not set (owner step: add the repository secret)"
  check_key
fi
mkdir -p "$APP"

if [ "$MODE" = install ]; then
  SOURCE=${SKIPPERCAST_SOURCE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}
  SHA=$(git -C "$SOURCE" rev-parse HEAD)
  [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "cannot read the checkout's commit"
  # The build (git, pip, the revision's own code) runs without the key in its environment:
  # same effect as `env -u AISSTREAM_API_KEY`, which cannot wrap a shell function.
  (unset AISSTREAM_API_KEY; build_revision "$SOURCE" "$SHA")
else
  if [ -n "$ROLLBACK_SHA" ]; then
    SHA=$ROLLBACK_SHA
  else
    SHA=$(basename "$(readlink "$APP/previous" 2>/dev/null || true)")
    [ -n "$SHA" ] || die "no app/previous revision; pass --rollback <sha> (ls -1t $APP)"
  fi
  [ -f "$APP/$SHA/.complete" ] || die "revision $SHA is not kept in $APP (ls -1t $APP)"
  [ "$SHA" != "$(current_sha)" ] || note "$SHA is already current; restarting it"
fi

SINCE=$(date +%s)
activate "$SHA"
wait_for_heartbeat "$SHA" "$SINCE"
prune
note "$UNIT is running $SHA"
