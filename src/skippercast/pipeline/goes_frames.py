"""GOES longwave frame-time index from the nowCOAST WMS GetCapabilities document.

    python -m skippercast.pipeline.goes_frames --output var/live-published/goes-times.json

Writes one `packages/coast` `CloudImage` record (`ocean-types.ts`): the
acquisition times the `goes_longwave_imagery` layer advertises, the newest of
them as `observedAt`, and the fetch time. No imagery is stored; the browser
requests WMS tiles pinned to a listed time (`cloudSource` in
`packages/coast/src/map-sources.ts`), never `current` or `latest`. Times come
only from the layer's own time dimension, never from the clock. The newest
frame must be at most 90 minutes old, or nothing is written and the last
published index stays, aging out of the same gate in the client. Ported from
`fish` `src/providers/ocean.ts` (`parseSatelliteCapabilities`).
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from xml.etree import ElementTree

from .. import http

HOST = "nowcoast.noaa.gov"
CAPABILITIES_URL = f"https://{HOST}/geoserver/observations/satellite/ows?service=WMS&request=GetCapabilities&version=1.3.0"
LAYER = "goes_longwave_imagery"
MAX_BODY = 250_000
MAX_AGE_MS = 90 * 60_000  # same gate as packages/coast cloudSource
FUTURE_SKEW_MS = 5 * 60_000  # publisher clock tolerance, as in fish
MAX_TIMES = 24
ATTRIBUTION = "NOAA / NESDIS · GOES East & West longwave infrared"
LIMITATIONS = ("Dated longwave infrared satellite mosaic: brightness temperature, not a cloud-cover percentage "
               "or underwater visibility measurement. Observed frames only, never a forecast; regional cloud "
               "patterns are coarser than individual beaches.")


def iso(ms):
    """Epoch milliseconds -> `YYYY-MM-DDTHH:MM:SS.mmmZ` (JavaScript `toISOString`, as the client compares strings)."""
    return datetime.fromtimestamp(ms // 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def epoch(value):
    """An ISO 8601 time with an explicit zone -> epoch ms; None for anything else (ranges, naive times)."""
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return round(moment.timestamp() * 1000) if moment.tzinfo else None


def local(tag):
    return tag.rsplit("}", 1)[-1]


def layer_times(xml):
    """The raw `time` dimension entries of the `goes_longwave_imagery` layer (WMS 1.3.0, namespace-agnostic)."""
    if b"<!DOCTYPE" in (xml if isinstance(xml, bytes) else xml.encode()):
        raise ValueError("Capabilities document carries a DOCTYPE")
    root = ElementTree.fromstring(xml)
    for layer in root.iter():
        if local(layer.tag) != "Layer":
            continue
        name = next((child.text for child in layer if local(child.tag) == "Name"), None)
        if (name or "").strip() != LAYER:
            continue
        for child in layer:
            if local(child.tag) == "Dimension" and child.get("name", "").lower() == "time" and child.text:
                return child.text.split(",")
        break
    raise ValueError("GOES observation time metadata unavailable")


def parse_capabilities(xml, now):
    """Capabilities document -> `CloudImage`. Raises ValueError when no listed frame passes the age gate."""
    clock = int(now.timestamp() * 1000)
    stamps = sorted({ms for ms in map(epoch, layer_times(xml)) if ms is not None and ms <= clock + FUTURE_SKEW_MS})
    if not stamps or clock - stamps[-1] > MAX_AGE_MS:
        raise ValueError("GOES imagery is stale or unavailable")
    times = [iso(ms) for ms in stamps[-MAX_TIMES:]]
    return {"id": "goes-longwave", "kind": "observation", "observedAt": times[-1], "fetchedAt": iso(clock),
            "availableTimes": times, "layer": LAYER, "url": f"https://{HOST}/",
            "attribution": ATTRIBUTION, "license": "public-domain-us-gov", "limitations": LIMITATIONS}


def collect(session, now=None):
    now = now or datetime.now(timezone.utc)
    body = session.get(CAPABILITIES_URL, timeout=20, max_bytes=MAX_BODY, allowed_hosts=[HOST],
                       allowed_prefixes=[f"https://{HOST}/geoserver/"]).body or b""
    return parse_capabilities(body, now)


def write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        record = collect(http.Session(allowed_hosts=[HOST]), now)
    except (OSError, ValueError, ElementTree.ParseError) as error:
        # The cycle continues; the last published index keeps its own clocks and ages out in the client.
        print(f"::warning title=GOES frame times::{type(error).__name__}: {str(error)[:300]}; kept the last index",
              file=sys.stderr)
        return 1
    write(args.output, record)
    print(json.dumps({"observedAt": record["observedAt"], "frames": len(record["availableTimes"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
