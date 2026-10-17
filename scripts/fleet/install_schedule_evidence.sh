#!/usr/bin/env bash
# Install the private twice-daily schedule-evidence collector as a user service.
set -euo pipefail

REGION=${1:-CA}
[[ "$REGION" == "CA" ]] || { echo "only the reviewed CA region is supported" >&2; exit 2; }
ROOT=$(git rev-parse --show-toplevel)
SCRIPT="$ROOT/scripts/fleet/schedule_evidence.py"
PYTHON=${SKIPPERCAST_FLEET_PYTHON:-"$HOME/.local/share/skippercast/app/current/.venv/bin/python"}
DATA="$HOME/.local/share/skippercast/fleet/$REGION/schedule-evidence"
CACHE="$HOME/.local/share/skippercast/fleet/$REGION/http-cache"
UNIT_DIR="$HOME/.config/systemd/user"
SERVICE="$UNIT_DIR/skippercast-schedule-evidence@.service"
TIMER="$UNIT_DIR/skippercast-schedule-evidence@.timer"

[ -f "$SCRIPT" ] || { echo "collector script missing from $ROOT" >&2; exit 1; }
[ -x "$PYTHON" ] || { echo "fleet Python runtime missing: $PYTHON" >&2; exit 1; }
case "$ROOT" in "$HOME"/*) ;; *) echo "worktree must be under the user home" >&2; exit 1 ;; esac
umask 0077
mkdir -p "$DATA" "$CACHE" "$UNIT_DIR"
chmod 0700 "$DATA"

cat > "$SERVICE" <<EOF
[Unit]
Description=SkipperCast private schedule and AIS evidence collection (%i)

[Service]
Type=oneshot
UMask=0077
WorkingDirectory=$ROOT
Environment=SKIPPERCAST_FLEET_VAR=$HOME/.local/share/skippercast/fleet
Environment=SKIPPERCAST_HTTP_CACHE=$CACHE
ExecStart=$PYTHON $SCRIPT --region %i --max-pages 20 --deadline-seconds 900
TimeoutStartSec=15min
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DATA $CACHE
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallArchitectures=native
EOF

cat > "$TIMER" <<'EOF'
[Unit]
Description=Run SkipperCast schedule-evidence collection twice daily (%i)

[Timer]
OnActiveSec=2min
OnUnitActiveSec=12h
AccuracySec=1min
Unit=skippercast-schedule-evidence@%i.service

[Install]
WantedBy=timers.target
EOF

chmod 0600 "$SERVICE" "$TIMER"
systemctl --user daemon-reload
systemctl --user enable --now "skippercast-schedule-evidence@$REGION.timer"
printf 'enabled %s\n' "skippercast-schedule-evidence@$REGION.timer"
systemctl --user list-timers --all --no-pager | grep "skippercast-schedule-evidence@$REGION.timer" || true
