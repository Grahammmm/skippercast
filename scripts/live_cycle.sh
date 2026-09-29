#!/usr/bin/env bash
# One live-conditions cycle: collect, publish to the `conditions` branch, check
# saved trips. Run from the repository root inside GitHub Actions.
#   scripts/live_cycle.sh [--intelligence] [--skip-trips]
set -euo pipefail
export PYTHONPATH=src

intelligence=0
trips=1
for arg in "$@"; do
  case "$arg" in
    --intelligence) intelligence=1 ;;
    --skip-trips) trips=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p var/live
# Load the last published generation. Later cycles reuse the worktree, which
# holds what this job last pushed; it is reloaded only if someone else published.
bash scripts/publish_branch_snapshot.sh --load conditions var/live-published
if [ -f var/live-published/latest.json ]; then
  cp var/live-published/latest.json var/live/previous.json
fi

# SkipperCast's own NOAA/ECMWF forecast tiles; a failure keeps the last published tiles.
if ! bash scripts/publish_forecasts.sh; then
  echo "::warning title=Forecast tiles::build or publish failed; models keep their last published tiles"
fi
if [ -f var/forecasts/index.json ]; then
  export SKIPPERCAST_FORECAST_ROOT=var/forecasts
fi

python scripts/refresh_regions.py live --output var/live --previous-root var/live-published
if [ "$intelligence" = 1 ] || [ ! -f var/live/intelligence-health.json ]; then
  python scripts/refresh_regions.py intelligence --output var/live --previous-root var/live-published
fi
python scripts/refresh_regions.py habitat --output var/live --previous-root var/live-published

# Publish.
cp var/live/latest.json var/live/intelligence-health.json var/live/habitat-health.json var/live-published/
mkdir -p var/live-published/regions
python scripts/prune_habitat_tiles.py var/live-published var/live
cp -R var/live/regions/. var/live-published/regions/
python - <<'PY'
from pathlib import Path
from skippercast.pipeline.verification_archive import prune_archive
for region in Path('var/live-published/regions').iterdir():
    if region.is_dir() and (region / 'verification-state.json').exists():
        prune_archive(region)
PY
cp docs/live-conditions.md var/live-published/README.md
# One parentless commit, force-pushed with a lease: the branch never grows history.
bash scripts/publish_branch_snapshot.sh conditions var/live-published 'Refresh regional ocean evidence and forecast archive'
echo "published"
bash scripts/publish_branch_r2.sh var/live-published conditions
# The site serves R2 first: confirm it now serves this cycle, not an older one.
if [ -n "${FEEDS_PUBLIC_BASE:-}" ]; then
  published_at=$(python -c 'import json; print(json.load(open("var/live-published/latest.json")).get("published_at", ""))')
  python scripts/verify_published_feed.py "${FEEDS_PUBLIC_BASE%/}/feeds/conditions/latest.json" \
    "${GITHUB_RUN_ID:-local}" --published-at "$published_at"
fi

if [ "$trips" = 1 ]; then
  python scripts/check_saved_trips.py
fi
