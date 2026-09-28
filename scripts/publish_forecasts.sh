#!/usr/bin/env bash
# Build SkipperCast forecast tiles when a newer NOAA/ECMWF cycle is out, and
# publish them to the `forecasts` branch as a single commit (no history growth).
# Safe to run every cycle: unchanged models are reused in seconds.
set -euo pipefail
export PYTHONPATH=src
out=var/forecasts
pub=var/forecasts-published

if [ ! -d "$pub" ]; then
  if git ls-remote --exit-code --heads origin forecasts >/dev/null; then
    git fetch -q origin forecasts --depth=1
    git worktree add -q --detach "$pub" FETCH_HEAD
  else
    mkdir -p "$pub"
    git -C "$pub" init -q -b forecasts
    git -C "$pub" remote add origin "$(git remote get-url origin)"
    git -C "$pub" config http.https://github.com/.extraheader "$(git config --get http.https://github.com/.extraheader)"
  fi
fi

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

rsync -a --delete --exclude .git "$out"/ "$pub"/
cp docs/forecast-data.md "$pub"/README.md
git -C "$pub" add -A
# index.json changes every run; publish only when tiles or manifests changed.
if git -C "$pub" diff --cached --name-only | grep -qv -e '^index.json$' -e '^README.md$'; then
  export GIT_AUTHOR_NAME='github-actions[bot]' GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com'
  export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
  tree=$(git -C "$pub" write-tree)
  commit=$(git -C "$pub" commit-tree "$tree" -m "SkipperCast forecast tiles $(date -u +%Y-%m-%dT%H:%MZ)")
  git -C "$pub" push -q --force origin "$commit:refs/heads/forecasts"
  git -C "$pub" reset -q --soft "$commit"
  echo "Published new forecast tiles."
else
  git -C "$pub" reset -q
  echo "Forecast tiles unchanged."
fi
