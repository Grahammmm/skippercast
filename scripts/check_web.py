"""Validate the static publication, its reviewed data copies, and local assets.

Claims recorded in audit receipts (no longer published with the app) are
checked by the claims pin test_receipt_claims.py under the research tests.
"""
from pathlib import Path
from html.parser import HTMLParser
import base64
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
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.refs.extend(value for key, value in attrs if key in {"src", "href"} and value)
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def check_page_references(path):
    """Resolve static resources; only registered navigation/RSS routes are dynamic."""
    parser = AssetParser()
    parser.feed(path.read_text())
    public_pages = {"/report", "/feed.xml", "/methodology", "/about"}
    for tag, attrs in parser.tags:
        for attribute in ("src", "href"):
            ref = attrs.get(attribute)
            if not ref:
                continue
            url = urlsplit(ref)
            if url.scheme or url.netloc or not url.path:
                continue
            navigation = tag == "a" and attribute == "href"
            rss = (tag == "link" and attribute == "href" and
                   attrs.get("rel") == "alternate" and
                   attrs.get("type") == "application/rss+xml" and ref == "/feed.xml")
            if (navigation and url.path in public_pages) or rss:
                router = (ROOT / "server/routes/coast-pages.ts").read_text()
                app = (ROOT / "server/app.ts").read_text()
                assert f"'{url.path}'" in router and "app.route('/', coastPages);" in app, (path, ref)
                continue
            if navigation and url.path == "/privacy":
                assets = (ROOT / "server/routes/assets.ts").read_text()
                assert "if(path === '/privacy') return '/privacy.html';" in assets, (path, ref)
                assert (WEB / "privacy.html").exists(), (path, ref)
                continue
            target = ((WEB / unquote(url.path).lstrip("/")) if url.path.startswith("/")
                      else (path.parent / unquote(url.path))).resolve()
            assert (target.is_relative_to(WEB) or target.is_relative_to(ROOT / "web")) and target.exists(), (path, ref)


def sri_digest(integrity, data):
    """True when one of the SRI tokens (sha256/384/512, base64) matches data."""
    for token in integrity.split():
        algorithm, _, value = token.partition("-")
        if algorithm in {"sha256", "sha384", "sha512"} and value:
            if base64.b64encode(hashlib.new(algorithm, data).digest()).decode() == value:
                return True
    return False


def check_vendor_integrity(pinned):
    """Every page that loads a vendored script or stylesheet pins it with SRI.

    The integrity value must match both the file and scripts/web-vendor-sha256.json,
    so a vendor update has to change all three together. Pages carry no meta CSP:
    the policy is sent as a header from server/security-headers.ts.
    """
    for path in WEB.glob("*.html"):
        text = path.read_text()
        assert 'http-equiv="Content-Security-Policy"' not in text, (path, "CSP belongs in server/security-headers.ts")
        parser = AssetParser()
        parser.feed(text)
        for tag, attrs in parser.tags:
            ref = attrs.get("src") if tag == "script" else attrs.get("href") if tag == "link" else None
            if not ref or not urlsplit(ref).path.startswith("vendor/"):
                continue
            if tag == "link" and attrs.get("rel") != "stylesheet":
                continue
            name = "dist/" + urlsplit(ref).path
            integrity = attrs.get("integrity") or ""
            assert integrity, (path, ref, "vendor asset needs an integrity attribute")
            assert name in pinned, (path, ref, "vendor asset missing from scripts/web-vendor-sha256.json")
            data = (ROOT / name).read_bytes()
            # The pinned sha256 was checked against the file above, so a match here
            # ties the tag, the file and the pin together.
            assert sri_digest(integrity, data), (path, ref, "integrity does not match the file")


def check_native_depth_review(name, scope):
    """Keep an incomplete native-source pass off the public coastal guide."""
    data = json.loads((WEB / 'data' / name).read_text())
    sectors = json.loads((WEB / 'data/coastal-sectors.json').read_text())['sectors']
    sector_ids = {row['id'] for row in sectors}
    assert data['scope'] == scope and data['status'] == 'ok' and not data['failed_survey_ids'], name
    assert data['survey_file_count'] == len(data['files']) and data['survey_file_count'] > 0, name
    assert {row['sector_id'] for row in data['sectors']} == sector_ids, name
    assert len(data['sectors']) == len(sector_ids), name
    assert len({row['bag_url'] for row in data['files']}) == len(data['files']), name
    expected = {sector_id: {'source_files_with_eligible_cells': 0,
                            'measured_native_cells': 0,
                            'depth_uncertainty_eligible_cells': 0}
                for sector_id in sector_ids}
    for source in data['files']:
        assert source['status'] == 'ok' and source['bag_sha256'], name
        assert set(source['sectors']) <= sector_ids, name
        counts = source['counts']
        assert 0 <= counts['depth_uncertainty_eligible_cells'] <= counts['measured_native_cells'], name
        for sector_id, values in source['sectors'].items():
            assert 0 <= values['depth_uncertainty_eligible_cells'] <= values['measured_native_cells'], name
            rollup = expected[sector_id]
            rollup['source_files_with_eligible_cells'] += values['depth_uncertainty_eligible_cells'] > 0
            for field in ('measured_native_cells', 'depth_uncertainty_eligible_cells'):
                rollup[field] += values[field]
    for row in data['sectors']:
        for key, value in expected[row['sector_id']].items():
            assert row[key] == value, (name, row['sector_id'], key)


def check_central_sediment_context():
    manifest = json.loads((ROOT / 'catalog/usgs-central-sediment-source.json').read_text())
    data = json.loads((WEB / 'data/usgs-central-thin-sediment-context.geojson').read_text())
    assert data['type'] == 'FeatureCollection'
    assert data['scope'] == 'usgs-central-interpreted-sediment-context'
    assert data['source']['raster_sha256'] == manifest['raster_sha256']
    assert data['source']['metadata_sha256'] == manifest['metadata_sha256']
    assert data['screen']['negative_source_cells_excluded'] > 0
    assert len(data['features']) >= 20
    for feature in data['features']:
        props = feature['properties']
        assert feature['geometry']['type'] in {'Polygon', 'MultiPolygon'}
        assert props['source_id'] == manifest['id']
        assert props['kind'] == 'estimated-thin-sediment'
        assert props['estimated_sediment_thickness_m'] == [0, manifest['screening_threshold_m']]
        assert all(props[key] is False for key in
                   ('fishing_target', 'exportable', 'depth_qualified', 'fish_confirmed'))


VERSIONED_NAME = re.compile(r"-v\d")


def check_no_versioned_client_names():
    """AGENTS.md: the build fingerprints assets, so never ship -vN copies."""
    versioned = sorted(path.name for path in WEB.iterdir() if VERSIONED_NAME.search(path.name))
    assert not versioned, f"versioned file names in dist/ (use the canonical name): {versioned}"


MARKUP_HOST = "web/app/CoastMarkup.tsx"
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs"}
# Every way web/ code could turn a string into DOM: innerHTML or outerHTML set
# by property (`.x =`, `+=`, never `==`), by unquoted object key
# (Object.assign(el, {innerHTML: s}); this also flags a type member of that
# name) or named in any quoted string (`el['innerHTML'] =`, Reflect.set,
# Object.defineProperty, a template-literal key), insertAdjacentHTML, Preact's
# dangerouslySetInnerHTML, document.write/writeln, setHTMLUnsafe,
# Range.createContextualFragment and DOMParser.parseFromString.
MARKUP_SINK = re.compile(
    r"\.\s*(?:inner|outer)HTML\s*\+?=(?!=)"
    r"|\b(?:inner|outer)HTML\s*:"
    r"|['\"`](?:inner|outer)HTML['\"`]"
    r"|\b(?:insertAdjacentHTML|dangerouslySetInnerHTML|setHTMLUnsafe|createContextualFragment|parseFromString)\b"
    r"|\bdocument\s*\.\s*write(?:ln)?\b")
# A `/` after one of these (or a keyword below, or at the start) begins a regex literal, not division.
REGEX_AFTER = set("(,=:[!&|?{};+-*%~^")
REGEX_KEYWORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"}


def _regex_end(source, i):
    """Index just past the regex literal starting at source[i] == '/', or None if the line ends first."""
    j, klass, n = i + 1, False, len(source)
    while j < n and source[j] != "\n":
        c = source[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            klass = True
        elif c == "]":
            klass = False
        elif c == "/" and not klass:
            j += 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            return j
        j += 1
    return None


def strip_comments(source):
    """Blank out // and /* */ comments, keeping strings, template literals, regex literals and line numbers."""
    out, i, n, quote = [], 0, len(source), None
    last = ""   # the last significant character emitted outside strings and comments
    while i < n:
        c = source[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if c == quote or (c == "\n" and quote != "`"):
                quote = None
                last = c
            i += 1
        elif c in "'\"`":
            quote = c
            out.append(c)
            i += 1
        elif source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end < 0 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in source[i:end]))
            i = end
        elif c == "/":
            word = re.search(r"([A-Za-z_$]+)\s*$", "".join(out[-20:]))
            regex = not last or last in REGEX_AFTER or bool(word and word.group(1) in REGEX_KEYWORDS)
            end = _regex_end(source, i) if regex else None
            out.append(source[i:end or i + 1])
            i = end or i + 1
            last = "/"
        else:
            out.append(c)
            if not c.isspace():
                last = c
            i += 1
    return "".join(out)


def markup_sinks(root=ROOT):
    """FE-75: only web/app/CoastMarkup.tsx may write markup into the DOM in web/ (comments ignored).

    This is static text matching, not analysis: a property name built at run
    time (`el['inner' + 'HTML']`, a variable holding the name) is not caught.
    Review owns that case; the rule catches every literal spelling.
    """
    found = []
    for path in sorted((root / "web").rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file() or relative == MARKUP_HOST:
            continue
        code = strip_comments(path.read_text())
        found += [f"{relative}:{code.count(chr(10), 0, m.start()) + 1}" for m in MARKUP_SINK.finditer(code)]
    return found


LEGAL_PAGES = ("terms.html", "privacy.html", "licenses.html")


def check_legal_pages():
    """Terms, privacy and licences exist, say they are drafts, and are reachable."""
    for name in LEGAL_PAGES:
        text = (WEB / name).read_text()
        assert "Draft — pending review by counsel" in text, name
        assert 'href="styles.css"' in text, name
    for page in ("index.html", "sources.html"):
        parser = AssetParser()
        parser.feed((WEB / page).read_text())
        missing = set(LEGAL_PAGES) - set(parser.refs)
        assert not missing, (page, sorted(missing))


def main():
    assert (WEB / "index.html").is_file()
    check_no_versioned_client_names()
    check_legal_pages()
    sinks = markup_sinks()
    assert not sinks, f"markup written into the DOM outside {MARKUP_HOST} (mount packages/coast markup through it): {sinks}"
    readiness = json.loads((WEB / 'data/california-atlas-readiness.json').read_text())
    usgs_leads = json.loads((WEB / 'data/usgs-ds781-source-leads.json').read_text())
    assert (WEB / 'data/usgs-ds781-source-leads.json').read_bytes() == (ROOT / 'catalog/usgs-ds781-source-leads.json').read_bytes()
    assert (WEB / 'data/usgs-ds781-metadata-review.json').read_bytes() == (ROOT / 'catalog/usgs-ds781-metadata-review.json').read_bytes()
    usgs_metadata = json.loads((WEB / 'data/usgs-ds781-metadata-review.json').read_text())
    assert usgs_metadata['record_count'] == len(usgs_metadata['records']) == 75
    assert len(usgs_leads['map_areas']) == 39
    assert all(area['priority_product_status'] != 'linked' or area['products']
               for area in usgs_leads['map_areas'])
    sectors = json.loads((WEB / 'data/coastal-sectors.json').read_text())['sectors']
    assert len(readiness['sectors']) == len(sectors) == 19
    assert {row['sector_id'] for row in readiness['sectors']} == {row['id'] for row in sectors}
    assert all(row['status'] in {'source-review-only', 'partial-local-targets'}
               and row['remaining_promotion_gates'] for row in readiness['sectors'])
    deep_by_sector = {row['sector_id']: row['native_depth_excluded_survey_ids']
                      for row in readiness['sectors']}
    assert deep_by_sector['morro-conception'] == ['H13089', 'H13151']
    assert deep_by_sector['cambria-morro'] == ['H13089', 'H13151']
    assert deep_by_sector['sur-san-simeon'] == ['H13151']
    assert all('usgs_ds781_map_area_leads' in row for row in readiness['sectors'])
    assert all('fgdc_metadata_reviewed' in lead for row in readiness['sectors']
               for lead in row['usgs_ds781_map_area_leads'])
    character = json.loads((WEB / 'data/usgs-ds781-native-character-review.json').read_text())
    assert character['scope'] == 'usgs-ds781-statewide-original-character-raster-audit'
    assert (character['product_count'], character['inspected_count'], character['held_count'], character['failed_count']) == (35, 17, 18, 0)
    assert sum(row.get('class_table_status') == 'verified' for row in character['products']) == 10
    assert character['fishing_target'] is False and character['exportable'] is False
    assert all('usgs_ds781_opened_native_character_rasters' in row for row in readiness['sectors'])
    cape_queue = json.loads((WEB / 'data/cape-mendocino-original-habitat-site-review-queue.json').read_text())
    cape_closures = json.loads((WEB / 'data/cape-mendocino-shortlist-closure-review.json').read_text())
    cape_context = json.loads((WEB / 'data/cape-mendocino-native-hard-context.geojson').read_text())
    assert cape_queue['research_shortlist_count'] == cape_closures['shortlist_count'] == 32
    assert cape_closures['held_count'] == 0 and cape_closures['buffer_m'] == 100
    assert cape_closures['fishing_target'] is False and cape_closures['exportable'] is False
    assert {row['context_id'] for row in cape_queue['research_shortlist']} == {
        row['context_id'] for row in cape_closures['outlines']}
    assert {row['context_id'] for row in cape_closures['outlines']} <= {
        feature['properties']['id'] for feature in cape_context['features']}
    assert cape_closures['input_sha256']['queue'] == hashlib.sha256(
        (WEB / 'data/cape-mendocino-original-habitat-site-review-queue.json').read_bytes()).hexdigest()
    assert cape_closures['input_sha256']['context'] == hashlib.sha256(
        (WEB / 'data/cape-mendocino-native-hard-context.geojson').read_bytes()).hexdigest()
    assert all(row['within_closure_review_buffer'] is False for row in cape_closures['outlines'])
    conception_queue = json.loads((WEB / 'data/point-conception-regular-site-review-queue.json').read_text())
    conception_closures = json.loads((WEB / 'data/point-conception-shortlist-closure-review.json').read_text())
    conception_context = json.loads((WEB / 'data/point-conception-native-hard-context.geojson').read_text())
    assert conception_queue['research_shortlist_count'] == conception_closures['shortlist_count'] == 4
    assert conception_closures['held_count'] == 0 and conception_closures['buffer_m'] == 100
    assert conception_closures['fishing_target'] is False and conception_closures['exportable'] is False
    assert {row['context_id'] for row in conception_queue['research_shortlist']} == {
        row['context_id'] for row in conception_closures['outlines']}
    assert {row['context_id'] for row in conception_closures['outlines']} <= {
        feature['properties']['id'] for feature in conception_context['features']}
    assert conception_closures['input_sha256']['queue'] == hashlib.sha256(
        (WEB / 'data/point-conception-regular-site-review-queue.json').read_bytes()).hexdigest()
    assert conception_closures['input_sha256']['context'] == hashlib.sha256(
        (WEB / 'data/point-conception-native-hard-context.geojson').read_bytes()).hexdigest()
    central_deep = json.loads((WEB / 'data/noaa-central-deepwater-native-depth-screen.json').read_text())
    assert central_deep['scope'] == 'noaa-original-central-coast-vr-depth-band-screen'
    assert {row['survey_id'] for row in central_deep['sources']} == {'H13089', 'H13151'}
    assert central_deep['fishing_target'] is False and central_deep['exportable'] is False
    assert all(row['raw_cells_in_25_to_200_ft_mllw_band'] == 0 and
               row['nearshore_depth_lead'] is False for row in central_deep['sources'])
    assert (WEB / "data/atlas.json").read_bytes() == (ATLAS / "data/atlas.json").read_bytes()
    for name in ["complete.gpx", "waypoints.gpx", "reef-outlines.gpx", "drift-lines.gpx", "spot-notes.html"]:
        assert (WEB / "downloads" / name).read_bytes() == (ATLAS / "exports" / name).read_bytes(), name
    assert (WEB / "downloads/LICENSE.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()
    pinned = json.loads((ROOT / "scripts/web-vendor-sha256.json").read_text())
    for name, digest in pinned.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    check_vendor_integrity(pinned)
    for path in WEB.rglob("*.html"):
        if path.relative_to(WEB).parts[0] in {"client","server"}:continue
        check_page_references(path)
    for path in WEB.rglob("*.css"):
        if path.relative_to(WEB).parts[0] in {"client","server"}:continue
        for ref in re.findall(r"url\(['\"]?([^)'\"]+)", path.read_text()):
            url = urlsplit(ref)
            if not url.scheme and url.path:
                assert (path.parent / unquote(url.path)).is_file(), (path, ref)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    full = ET.parse(WEB / "downloads/complete.gpx").getroot()
    assert len(full.findall("g:wpt", ns)) == 132
    for path in (WEB / "downloads").glob("*.gpx"):
        assert ET.parse(path).getroot().tag == "{http://www.topografix.com/GPX/1/1}gpx"
    check_native_depth_review('noaa-vr-native-depth-review.json',
                              'california-original-vr-native-depth-review')
    check_native_depth_review('noaa-regular-native-depth-review.json',
                              'california-original-regular-native-depth-review')
    check_central_sediment_context()
    print("Website entrypoints, asset references, vendor hashes and SRI, GPX, and canonical data copies passed.")


if __name__ == "__main__":
    main()
