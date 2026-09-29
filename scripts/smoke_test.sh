#!/usr/bin/env bash
# Smoke-test a deployed SkipperCast site. Usage: scripts/smoke_test.sh https://site [build-id]
# Pass "" as the build id to skip the build match. The build id defaults to the one in dist/client (the build just deployed); the
# test waits up to two minutes for that build to be served, then checks pages,
# feeds, the service worker and that forged identity headers are refused.
set -euo pipefail
SITE=${1:?usage: smoke_test.sh <site-url> [build-id]}
SITE=${SITE%/}
BUILD=${2-$(ls dist/client/index.*.html 2>/dev/null | sed -E 's#.*/index\.([0-9a-f]{10})\.html#\1#' | head -1)}
fail() { echo "::error::Smoke test: $*"; exit 1; }
get() { curl -fsS --max-time 20 "$@"; }
has() { case "$1" in *"$2"*) return 0;; *) return 1;; esac; }

for attempt in $(seq 1 12); do
  health=$(get "$SITE/api/health" || true)
  served=$(printf '%s' "$health" | python3 -c "import json,sys;print(json.load(sys.stdin).get('build',''))" 2>/dev/null || true)
  if [ -z "$BUILD" ] || [ "$served" = "$BUILD" ]; then break; fi
  echo "Waiting for build $BUILD (serving '${served:-none}')…"; sleep 10
done
has "$health" '"service":"SkipperCast"' || fail "/api/health did not identify SkipperCast: $health"
[ -z "$BUILD" ] || [ "$served" = "$BUILD" ] || fail "site serves build '$served', expected '$BUILD'"
echo "health ok (build ${served:-unknown})"

# Read whole bodies before matching: with pipefail, "curl | grep -q" fails when
# grep exits early and curl gets SIGPIPE on the rest of the page.
home=$(get "$SITE/") || fail "home page not served"
case "$home" in *'<title>'*) ;; *) fail "home page has no <title>";; esac
echo "home page ok"

sw=$(curl -fsS -D - -o /dev/null --max-time 20 "$SITE/sw.js") || fail "/sw.js not served"
# Either the Worker's no-cache (ChatGPT Sites) or Cloudflare static assets'
# default "max-age=0, must-revalidate": both force revalidation on every check.
grep -qiE '^cache-control:.*(no-cache|max-age=0)' <<<"$sw" || fail "/sw.js must be revalidated on every request (no-cache or max-age=0)"
echo "service worker ok"

get "$SITE/feeds/conditions/latest.json" | python3 -c "import json,sys;json.load(sys.stdin)" || fail "live feed is not valid JSON"
echo "live feed ok"

forged=$(get -H 'oai-authenticated-user-id: smoke-test' -H 'oai-authenticated-user-email: smoke@example.test' "$SITE/api/session")
has "$forged" '"signedIn":false' || fail "a forged identity header was accepted: $forged"
echo "identity headers refused"
echo "Smoke test passed for $SITE"
