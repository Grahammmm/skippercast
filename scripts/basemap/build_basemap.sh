#!/usr/bin/env bash
# Build the Chart basemap archive (FE-10, docs/plans/front-end/design.md § 4 option 1).
#
#   scripts/basemap/build_basemap.sh [BUILD] [OUT_DIR] [--publish]
#
# BUILD is a Protomaps daily build (YYYYMMDD; blank or "latest" picks the newest).
# `pmtiles extract` reads only the byte ranges it needs from that planet build
# (no planet download): zooms 0-10 over the overview box, zooms 11-14 inside
# each active and preview region. The two extracts hold different zooms, so
# `pmtiles merge` joins them without re-encoding into
# OUT_DIR/ca-coast-BUILD.pmtiles, with OUT_DIR/manifest.json beside it (bytes,
# SHA-256, build seconds, source build). --publish uploads both to R2 as
# tiles/basemap/ (scripts/basemap/regions.py publish).
# Needs the pmtiles CLI (go-pmtiles); set PMTILES to its path if not on PATH.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
build=${1:-latest}
out=${2:-var/basemap}
publish=${3:-}
pmtiles=${PMTILES:-pmtiles}
regions() { python "$here/regions.py" "$@"; }

mkdir -p -- "$out"
if [ "$build" = latest ]; then build=$(regions latest); fi
# Keep the old build intact until the new archive and manifest are ready.
stage=$(mktemp -d -- "$out/.basemap-build.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
plan=$(regions plan --build "$build" --dir "$stage")
read -r source overview overview_max detail_min detail_max archive <<< "$plan"
python "$here/check_detail.py" --dir "$stage"
start=$(date +%s)
"$pmtiles" extract "$source" "$stage/overview.pmtiles" --bbox="$overview" --minzoom=0 --maxzoom="$overview_max"
"$pmtiles" extract "$source" "$stage/detail.pmtiles" --region="$stage/detail.geojson" --minzoom="$detail_min" --maxzoom="$detail_max"
"$pmtiles" merge "$stage/overview.pmtiles" "$stage/detail.pmtiles" "$stage/$archive"
"$pmtiles" verify "$stage/$archive"
seconds=$(( $(date +%s) - start ))
regions manifest --seconds "$seconds" --dir "$stage"
# Same filesystem: rename finished files into place, with the manifest last.
mv -f -- "$stage/plan.json" "$stage/detail.geojson" "$stage/$archive" "$stage/manifest.json" "$out/"
if [ "$publish" = --publish ]; then regions publish --dir "$out"; fi
