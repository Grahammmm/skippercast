#!/bin/sh
# PERF-BASELINE-1: the private-layer test pages, served locally by serve_range.py (never deployed).
#   checkout A (origin/main):                  python3 research/scripts/map_style/serve_range.py 18772
#   checkout B (claude/mapstyle-2-relief tip): python3 research/scripts/map_style/serve_range.py 18781
# with the retained private archives and layer files under each checkout's ignored var/ (see the report, A.1).
set -e
for prof in desktop phone; do
  node reports/perf/measure.mjs --base http://127.0.0.1:18781 --pages layers-relief --runs 3 --profiles $prof --quiet-ms 2000 --cap-ms 120000 --out reports/perf/raw/layers-relief-$prof.json
  node reports/perf/measure.mjs --base http://127.0.0.1:18772 --pages layers-main --runs 3 --profiles $prof --quiet-ms 2000 --cap-ms 120000 --out reports/perf/raw/layers-main-$prof.json
done
