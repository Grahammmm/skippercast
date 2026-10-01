#!/bin/sh
# Stand-in for `npx wrangler` in tests/test_wrangler_config.mjs. Logs every call to
# $FAKE_LOG; `r2 object get/put` read and write one stored object at $FAKE_STORE;
# `d1 list` returns no databases so the deploy stops right after the key check.
echo "$@" >> "$FAKE_LOG"
file=""
prev=""
for arg in "$@"; do [ "$prev" = "--file" ] && file="$arg"; prev="$arg"; done
case "$*" in
  *"r2 object get"*)
    # FAKE_R2_FAIL simulates a failure other than a missing object (auth, outage).
    [ -n "$FAKE_R2_FAIL" ] && { echo "$FAKE_R2_FAIL" >&2; exit 1; }
    [ -f "$FAKE_STORE" ] || { echo "The specified key does not exist. [code: 10007]" >&2; exit 1; }
    cp "$FAKE_STORE" "$file";;
  *"r2 object put"*) cp "$file" "$FAKE_STORE";;
  *"d1 list"*) echo '[]';;
esac
exit 0
