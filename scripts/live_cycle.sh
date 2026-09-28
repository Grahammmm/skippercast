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
# Load the last published generation once; later cycles reuse the worktree,
# which always holds what this job last pushed.
if [ ! -d var/live-published ] && git ls-remote --exit-code --heads origin conditions >/dev/null; then
  git fetch origin conditions --depth=1
  git worktree add --detach var/live-published FETCH_HEAD
fi
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
if [ ! -d var/live-published ]; then
  mkdir -p var/live-published
  git -C var/live-published init -b conditions
  git -C var/live-published remote add origin "$(git remote get-url origin)"
  git -C var/live-published config http.https://github.com/.extraheader "$(git config --get http.https://github.com/.extraheader)"
fi
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
git -C var/live-published config user.name 'github-actions[bot]'
git -C var/live-published config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C var/live-published add latest.json intelligence-health.json habitat-health.json regions README.md
git -C var/live-published diff --cached --quiet || git -C var/live-published commit -q -m 'Refresh regional ocean evidence and forecast archive'
git -C var/live-published push -q origin HEAD:refs/heads/conditions
echo "published"

if [ "$trips" = 1 ]; then
  python scripts/check_saved_trips.py
fi
