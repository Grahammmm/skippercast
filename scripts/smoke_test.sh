#!/usr/bin/env bash
# Smoke-test a deployed SkipperCast site. Usage: scripts/smoke_test.sh https://site [build-id]
# Pass "" as the build id to skip the build match. The build id defaults to the one stamped on dist/client's pages (the build just deployed); the
# test waits up to two minutes for that build to be served, then checks pages (/, /map, /coast),
# feeds, the service worker and that forged identity headers are refused.
set -euo pipefail
SITE=${1:?usage: smoke_test.sh <site-url> [build-id]}
SITE=${SITE%/}
# Every page is stamped NAME.<build>.html (FE-61 removed index.html). A glob, not ls: under pipefail a failed ls aborts the script.
if [ "$#" -lt 2 ]; then
  BUILD=
  for page in dist/client/*.*.html; do
    [[ $page =~ \.([0-9a-f]{10})\.html$ ]] && { BUILD=${BASH_REMATCH[1]}; break; }
  done
else
  BUILD=$2
fi
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

# FE-60: /map and /coast. On the current Worker / is the landing, /map the app
# and /coast redirects to it; after a rollback to a Worker built before FE-61
# / is the v1 shell, /map is dark and answers only with ?ui=v2, and /coast is
# the standalone page. Either way each must end at a page.
if has "$home" 'class="landing-body"'; then map_path=/map; else map_path='/map?ui=v2'; fi
map=$(get "$SITE$map_path") || fail "$map_path not served"
has "$map" '<title>' || fail "$map_path has no <title>"
echo "map page ok ($map_path)"
coast=$(get -L "$SITE/coast") || fail "/coast not served"
has "$coast" '<title>' || fail "/coast has no <title>"
echo "coast page ok"

sw=$(curl -fsS -D - -o /dev/null --max-time 20 "$SITE/sw.js") || fail "/sw.js not served"
# Either the Worker's no-cache or Cloudflare static assets'
# default "max-age=0, must-revalidate": both force revalidation on every check.
grep -qiE '^cache-control:.*(no-cache|max-age=0)' <<<"$sw" || fail "/sw.js must be revalidated on every request (no-cache or max-age=0)"
echo "service worker ok"

get "$SITE/feeds/conditions/latest.json" | python3 -c "import json,sys;json.load(sys.stdin)" || fail "live feed is not valid JSON"
echo "live feed ok"

session=$(get "$SITE/api/session")
has "$session" '"publicKey":"' || fail "/api/session has no Web Push public key: VAPID secrets are not deployed"
echo "push public key ok"

forged=$(get -H 'oai-authenticated-user-id: smoke-test' -H 'oai-authenticated-user-email: smoke@example.test' "$SITE/api/session")
has "$forged" '"signedIn":false' || fail "a forged identity header was accepted: $forged"
echo "identity headers refused"
echo "Smoke test passed for $SITE"
