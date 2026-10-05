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
#   bash scripts/advisor/relay-cleanup.sh            delete (prints each file and a total)
#   bash scripts/advisor/relay-cleanup.sh --dry-run  list what would go, delete nothing
#   bash scripts/advisor/relay-cleanup.sh --plist    print the launchd agent (Sundays 04:30)
set -euo pipefail

DAYS="${RELAY_CLEANUP_DAYS:-7}"
[[ "$DAYS" =~ ^[0-9]{1,3}$ ]] || { echo "RELAY_CLEANUP_DAYS must be a whole number of days" >&2; exit 2; }
BB="$HOME/Library/Application Support/bluebubbles-server"
DIRS=("$BB/Attachments" "$BB/Convert" "$HOME/Library/Messages/Attachments/BlueBubbles")
LABEL=com.skippercast.relay-cleanup
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

case "${1:-}" in
  --plist)
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

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) relay cleanup: files older than $DAYS days$([ "$DRY" = 1 ] && echo ' (dry run)')"
total=0
for dir in "${DIRS[@]}"; do
  [ -d "$dir" ] || continue
  # find -mtime +N: modified more than N whole days ago. -print0 keeps odd file names intact.
  # A permission error (Full Disk Access missing for ~/Library/Messages) is printed, not hidden.
  while IFS= read -r -d '' file; do
    echo "  ${file#"$HOME"/}"
    if [ "$DRY" = 0 ]; then rm -f -- "$file"; fi
    total=$((total + 1))
  done < <(find "$dir" -type f -mtime +"$DAYS" -print0 || true)
  if [ "$DRY" = 0 ]; then find "$dir" -mindepth 1 -type d -empty -delete 2>/dev/null || true; fi
done
echo "relay cleanup: $total file(s) $([ "$DRY" = 1 ] && echo 'would be deleted' || echo 'deleted')"
