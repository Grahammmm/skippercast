#!/usr/bin/env bash
# Weekly cleanup on the Text Advisor's relay Mac (docs/operations/runbooks/advisor-relay-setup.md
# § 12; docs/legal/threat-model.md § 9.2). BlueBubbles keeps its own copies of attachments it
# handles; Messages' "Keep Messages: 30 Days" never reaches them. This deletes those copies once
# they are older than 7 days (RELAY_CLEANUP_DAYS), then any folder left empty.
#
# Folders, from the BlueBubbles server source (packages/server/src/server/fileSystem/index.ts,
# FileSystem.attachmentsDir, attachmentCacheDir, convertDir and messagesAttachmentsDir):
#   ~/Library/Application Support/bluebubbles-server/Attachments   (Cached/ inside it included)
#   ~/Library/Application Support/bluebubbles-server/Convert
#   ~/Library/Messages/Attachments/BlueBubbles                     (macOS 12+ outgoing copies)
# Nothing else is touched: not Messages' own attachments or chat.db (Keep Messages governs
# those), not BlueBubbles' settings, certificates or contacts.
#
#   bash scripts/advisor/relay-cleanup.sh            delete (counts by role and in total)
#   bash scripts/advisor/relay-cleanup.sh --dry-run  count what would go, delete nothing
#   bash scripts/advisor/relay-cleanup.sh --plist    print the launchd agent (Sundays 04:30)
# An incomplete scan or removal logs a role-only diagnostic and exits nonzero.
set -euo pipefail

DAYS="${RELAY_CLEANUP_DAYS:-7}"
[[ "$DAYS" =~ ^[0-9]{1,3}$ ]] || { echo "RELAY_CLEANUP_DAYS must be a whole number of days" >&2; exit 2; }
BB="$HOME/Library/Application Support/bluebubbles-server"
LABEL=com.skippercast.relay-cleanup

case "${1:-}" in
  --plist)
    SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
    cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SELF</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/$LABEL.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/$LABEL.log</string>
</dict>
</plist>
PLIST
    exit 0 ;;
  --dry-run) DRY=1 ;;
  "") DRY=0 ;;
  *) echo "usage: relay-cleanup.sh [--dry-run | --plist]" >&2; exit 2 ;;
esac

count_files() {
  local file count=0 failed=0
  while IFS= read -r -d '' file; do
    if [[ "$DRY" == 1 ]] || rm -f -- "$file" 2>/dev/null; then
      count=$((count + 1))
    else
      failed=1
    fi
  done
  printf '%s\n' "$count"
  return "$failed"
}

clean_role() {
  local role="$1" dir="$2" count suffix=''
  if [[ ! -d "$dir" ]]; then
    # A missing optional root is normal; an unsearchable ancestor is not.
    local parent="$dir"
    while [[ "$parent" != / && ! -d "$parent" ]]; do
      parent="${parent%/*}"
      parent="${parent:-/}"
    done
    if [[ -x "$parent" ]]; then
      printf 'relay cleanup: %s: 0 file(s) %s (not present)\n' "$role" "$action"
      return 0
    fi
  fi

  # NUL-delimited paths stay in the pipe. pipefail retains both find and rm
  # failures; neither command's raw (path-bearing) diagnostics reach the log.
  if ! count=$(find "$dir" -type f -mtime +"$DAYS" -print0 2>/dev/null | count_files); then
    printf 'relay cleanup: %s: scan or file removal incomplete\n' "$role" >&2
    suffix=' (partial)'
  elif [[ "$DRY" == 0 ]] && ! find "$dir" -mindepth 1 -type d -empty -delete >/dev/null 2>&1; then
    printf 'relay cleanup: %s: empty-directory removal incomplete\n' "$role" >&2
    suffix=' (partial)'
  fi
  printf 'relay cleanup: %s: %s file(s) %s%s\n' "$role" "$count" "$action" "$suffix"
  total=$((total + count))
  if [[ -n "$suffix" ]]; then partial="$suffix"; fi
}

action=deleted
mode=''
if [[ "$DRY" == 1 ]]; then action='would be deleted'; mode=' (dry run)'; fi
printf '%s relay cleanup: files older than %s days%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$DAYS" "$mode"
total=0
partial=''
clean_role attachments "$BB/Attachments"
clean_role convert "$BB/Convert"
clean_role messages-copies "$HOME/Library/Messages/Attachments/BlueBubbles"
printf 'relay cleanup: %s file(s) %s%s\n' "$total" "$action" "$partial"
if [[ -n "$partial" ]]; then exit 1; fi
