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
regions() { python "$here/regions.py" "$@" --dir "$out"; }

mkdir -p "$out"
if [ "$build" = latest ]; then build=$(python "$here/regions.py" latest); fi
read -r source overview overview_max detail_min detail_max archive < <(regions plan --build "$build")
rm -f "$out/overview.pmtiles" "$out/detail.pmtiles" "$out/$archive"
start=$(date +%s)
"$pmtiles" extract "$source" "$out/overview.pmtiles" --bbox="$overview" --minzoom=0 --maxzoom="$overview_max"
"$pmtiles" extract "$source" "$out/detail.pmtiles" --region="$out/detail.geojson" --minzoom="$detail_min" --maxzoom="$detail_max"
"$pmtiles" merge "$out/overview.pmtiles" "$out/detail.pmtiles" "$out/$archive"
"$pmtiles" verify "$out/$archive"
seconds=$(( $(date +%s) - start ))
rm -f "$out/overview.pmtiles" "$out/detail.pmtiles"
regions manifest --seconds "$seconds"
if [ "$publish" = --publish ]; then regions publish; fi
