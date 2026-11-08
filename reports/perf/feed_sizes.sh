#!/bin/sh
# PERF-BASELINE-1: wire (encoded) and decoded sizes of the daily feed and brief payloads. One GET each, public read.
# Usage (repo root): sh reports/perf/feed_sizes.sh > reports/perf/raw/feed-sizes.tsv
B=https://skippercast.com
printf 'url\tstatus\twire_bytes_zstd_br_gzip\tdecoded_bytes\tcontent_encoding\tcache_control\n'
for p in '/api/daily?region=morro-bay' '/api/daily?region=morro-bay&part=brief' '/api/daily?region=morro-bay&part=regulations' '/api/daily?region=morro-bay&part=mpa-boundaries' '/api/daily?region=morro-bay&part=additional-closures' '/api/forecast?region=morro-bay' '/api/coast/report' '/api/coast/ocean' '/data/protected-areas.geojson' '/regions/morro-bay/land-water-lines.json' '/feeds/tiles/seafloor/regions/morro-bay/ledger.json'; do
  wire=$(curl -s -o /dev/null -H 'Accept-Encoding: zstd, br, gzip' -w '%{http_code}\t%{size_download}' "$B$p")
  dec=$(curl -s -H 'Accept-Encoding: identity' "$B$p" | wc -c)
  hdr=$(curl -s -o /dev/null -D - -H 'Accept-Encoding: zstd, br, gzip' "$B$p" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-encoding"{e=$2} tolower($1)=="cache-control"{c=$2} END{printf "%s\t%s", e, c}')
  printf '%s\t%s\t%s\t%s\n' "$p" "$wire" "$dec" "$hdr"
done
