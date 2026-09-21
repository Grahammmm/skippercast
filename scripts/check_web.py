"""Validate the static publication, its reviewed data copies, and local assets."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json
import re
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dist"
ATLAS = ROOT / "atlas/avila-point-estero-2026-09-20"


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        self.refs.extend(value for key, value in attrs if key in {"src", "href"} and value)


def main():
    assert (WEB / "index.html").is_file()
    assert (WEB / "data/atlas.json").read_bytes() == (ATLAS / "data/atlas.json").read_bytes()
    for name in ["complete.gpx", "waypoints.gpx", "reef-outlines.gpx", "drift-lines.gpx", "spot-notes.html"]:
        assert (WEB / "downloads" / name).read_bytes() == (ATLAS / "exports" / name).read_bytes(), name
    assert (WEB / "downloads/LICENSE.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()
    for name, digest in json.loads((ROOT / "scripts/web-vendor-sha256.json").read_text()).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    for path in WEB.rglob("*.html"):
        parser = AssetParser()
        parser.feed(path.read_text())
        for ref in parser.refs:
            url = urlsplit(ref)
            if url.scheme or url.netloc or not url.path:
                continue
            target = (path.parent / unquote(url.path)).resolve()
            assert target.is_relative_to(WEB) and target.exists(), (path, ref)
    for path in WEB.rglob("*.css"):
        for ref in re.findall(r"url\(['\"]?([^)'\"]+)", path.read_text()):
            url = urlsplit(ref)
            if not url.scheme and url.path:
                assert (path.parent / unquote(url.path)).is_file(), (path, ref)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    full = ET.parse(WEB / "downloads/complete.gpx").getroot()
    assert len(full.findall("g:wpt", ns)) == 132
    for path in (WEB / "downloads").glob("*.gpx"):
        assert ET.parse(path).getroot().tag == "{http://www.topografix.com/GPX/1/1}gpx"
    print("Website entrypoints, asset references, vendor hashes, GPX, and canonical data copies passed.")


if __name__ == "__main__":
    main()
