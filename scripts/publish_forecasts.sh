#!/usr/bin/env bash
# Build SkipperCast forecast tiles when a newer NOAA/ECMWF cycle is out, and
# publish them to the `forecasts` branch as a single commit (no history growth).
# Safe to run every cycle: unchanged models are reused in seconds.
set -euo pipefail
export PYTHONPATH=src
out=var/forecasts
pub=var/forecasts-published
mkdir -p var

# Reloaded only when another job (the manual Forecast tiles workflow) published.
bash scripts/publish_branch_snapshot.sh --load forecasts "$pub"

# FORCE=1 rebuilds every model even when its newest cycle is already published.
python -m skippercast.forecast.build --output "$out" --previous "$pub" ${FORCE:+--force} > var/forecast-build.json
python - <<'PY'
import json
index = json.load(open('var/forecast-build.json'))
for model, state in index['models'].items():
    if state['status'] != 'ok':
        print(f"::warning title=Forecast model {model}::{state.get('issue')} (kept previous: {state.get('kept_previous')})")
    else:
        print(f"{model}: {state['state']} {state['cycle']}")
PY

# GEFS wind-ensemble members at the regions' forecast points (no tiles). A failure
# keeps the previous build and must not stop the tiles from publishing.
if ! python -m skippercast.forecast.ensemble --output "$out" --previous "$pub" ${FORCE:+--force} > var/forecast-ensemble.json; then
  echo "::warning title=GEFS wind ensemble::build failed and no previous build exists"
fi
python - <<'PY'
import json
try:
    report = json.load(open('var/forecast-ensemble.json'))
except (OSError, ValueError):
    report = {'ncep_gefs025': {'status': 'failed', 'issue': 'no build report'}}
for model, state in report.items():
    if state['status'] != 'ok':
        print(f"::warning title=Forecast model {model}::{state.get('issue')} (kept previous: {state.get('kept_previous')})")
    else:
        print(f"{model}: {state['state']} {state['cycle']}")
PY

rsync -a --delete --exclude .git "$out"/ "$pub"/
cp docs/forecast-data.md "$pub"/README.md
git -C "$pub" add -A
# index.json changes every run; publish only when tiles or manifests changed.
if git -C "$pub" diff --cached --name-only | grep -qv -e '^index.json$' -e '^README.md$'; then
  bash scripts/publish_branch_snapshot.sh forecasts "$pub" "SkipperCast forecast tiles $(date -u +%Y-%m-%dT%H:%MZ)"
  echo "Published new forecast tiles."
else
  git -C "$pub" reset -q
  echo "Forecast tiles unchanged."
fi
# Sync R2 every run, not only when tiles changed, so a new or emptied bucket fills
# on the next run. The sync is hash-indexed, so unchanged files are not re-uploaded.
bash scripts/publish_branch_r2.sh "$pub" forecasts
