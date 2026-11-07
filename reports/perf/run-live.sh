#!/bin/sh
# PERF-BASELINE-1: the live-site baseline, one profile after the other (never in parallel). Run from the repo root.
set -e
node reports/perf/measure.mjs --base https://skippercast.com --pages live --runs 3 --profiles desktop --cap-ms 90000 --out reports/perf/raw/live-desktop.json
node reports/perf/measure.mjs --base https://skippercast.com --pages live --runs 3 --profiles phone --cap-ms 150000 --out reports/perf/raw/live-phone.json
# The same phone CPU on fast Wi-Fi, brief and saved-home map only (what slow 4G hides behind the export's 60 s timeout).
node reports/perf/measure.mjs --base https://skippercast.com --pages live --only brief,map-home --runs 3 --profiles phone-wifi --cap-ms 150000 --out reports/perf/raw/live-phone-wifi.json
