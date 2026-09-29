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

for attempt in $(seq 1 12); do
  health=$(get "$SITE/api/health" || true)
  served=$(printf '%s' "$health" | python3 -c "import json,sys;print(json.load(sys.stdin).get('build',''))" 2>/dev/null || true)
  if [ -z "$BUILD" ] || [ "$served" = "$BUILD" ]; then break; fi
  echo "Waiting for build $BUILD (serving '${served:-none}')…"; sleep 10
done
printf '%s' "$health" | grep -q '"service":"SkipperCast"' || fail "/api/health did not identify SkipperCast: $health"
[ -z "$BUILD" ] || [ "$served" = "$BUILD" ] || fail "site serves build '$served', expected '$BUILD'"
echo "health ok (build ${served:-unknown})"

get "$SITE/" | grep -q '<title>' || fail "home page has no <title>"
echo "home page ok"

sw=$(curl -fsS -D - -o /dev/null --max-time 20 "$SITE/sw.js") || fail "/sw.js not served"
printf '%s' "$sw" | grep -qi '^cache-control: no-cache' || fail "/sw.js must be served with Cache-Control: no-cache"
echo "service worker ok"

get "$SITE/feeds/conditions/latest.json" | python3 -c "import json,sys;json.load(sys.stdin)" || fail "live feed is not valid JSON"
echo "live feed ok"

forged=$(get -H 'oai-authenticated-user-id: smoke-test' -H 'oai-authenticated-user-email: smoke@example.test' "$SITE/api/session")
printf '%s' "$forged" | grep -q '"signedIn":false' || fail "a forged identity header was accepted: $forged"
echo "identity headers refused"
echo "Smoke test passed for $SITE"
