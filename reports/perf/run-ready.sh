#!/bin/sh
# PERF-BASELINE-1 round 2: readiness runs (screencast frames + input-delay probes + a drag probe), one load at a time, never in parallel.
# Run from the repository root with the two local servers up (see run-layers.sh). FRAMES is scratch space (frames are not committed).
set -e
FRAMES=${FRAMES:-/tmp/perf-frames}
R=reports/perf/raw
# live site, map pages cold; then the brief and the returning-visitor map also warm
node reports/perf/readiness.mjs --base https://skippercast.com --pages live --profiles desktop --runs 3 --cap-ms 90000 --out $R/ready-live-desktop.json --frames $FRAMES
node reports/perf/readiness.mjs --base https://skippercast.com --pages live --profiles phone --runs 3 --cap-ms 150000 --out $R/ready-live-phone.json --frames $FRAMES
node reports/perf/readiness.mjs --base https://skippercast.com --pages live --only brief,map-home-returning --passes cold,warm --profiles desktop --runs 3 --cap-ms 90000 --out $R/ready-live-desktop-warm.json --frames $FRAMES
# the phone CPU on an unthrottled network: the window in which the CPU duty cycle is measured with its own clock
node reports/perf/readiness.mjs --base https://skippercast.com --pages live --only brief,map-home-returning --profiles phone-wifi --runs 3 --cap-ms 150000 --out $R/ready-live-phone-wifi.json --frames $FRAMES
# local test pages for the private layers (servers: checkout A on 18772 = origin/main, checkout B on 18781 = claude/mapstyle-2-relief)
for prof in desktop phone; do
  node reports/perf/readiness.mjs --base http://127.0.0.1:18781 --pages layers-relief --profiles $prof --runs 3 --quiet-ms 2000 --cap-ms 120000 --out $R/ready-layers-relief-$prof.json --frames $FRAMES
  node reports/perf/readiness.mjs --base http://127.0.0.1:18772 --pages layers-main --profiles $prof --runs 3 --quiet-ms 2000 --cap-ms 120000 --out $R/ready-layers-main-$prof.json --frames $FRAMES
done
