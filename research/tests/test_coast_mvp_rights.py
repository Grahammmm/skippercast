"""Offline acceptance and fail-closed metadata checks for the C5 export."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
import subprocess
import sys

import pytest

from research.lib.paths import ROOT
from research.scripts.coast_mvp.coast_rights import render_manifest

FIXTURE = ROOT / "research/tests/fixtures/coast_mvp/rights-manifest.json"
SCRIPT = ROOT / "research/scripts/coast_mvp/coast_rights.py"


@pytest.fixture
def manifest():
    return json.loads(FIXTURE.read_text())


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.tags = []
        self.links = []

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.links.extend(value for key, value in attrs if key == "href")


def test_every_actual_contributor_has_license_attribution_and_provenance(manifest):
    page = render_manifest(manifest)
    parsed = Page()
    parsed.feed(page)
    text = " ".join(parsed.text)
    used = [row for row in manifest["sources"] if row["contributed_cells"] > 0]
    assert len(used) == 4
    for row in used:
        for value in (row["source_id"], row["name"], row["sha256"],
                      row["rights"]["license"], row["rights"]["attribution"]):
            assert value in text
        assert row["source_url"] in parsed.links
        assert row["rights"]["terms_url"] in parsed.links
    assert "fixture-unused-input" not in page
    assert "CC0-1.0" in text
    assert "US public domain" in text
    assert "GEBCO Bathymetric Compilation Group 2026" in text
    assert "Not for navigation" in text
    assert "review_required" in text
    assert "needs_permission" in text
    assert "non-profit use with acknowledgment" in text
    assert "For-profit permission question" in text
    assert "GEBCO, the IHO or the IOC" in text
    assert "script" not in parsed.tags


def test_deterministic_and_sorted(manifest):
    page = render_manifest(manifest)
    shuffled = deepcopy(manifest)
    shuffled["sources"].reverse()
    # Input identity changes, but contributor order remains deterministic.
    reversed_page = render_manifest(shuffled)
    assert page == render_manifest(manifest)
    for text in (page, reversed_page):
        assert text.index("fixture-csumb") < text.index("fixture-gebco-2026")


@pytest.mark.parametrize("field,value", [
    ("contributed_cells", None), ("contributed_cells", True),
    ("contributed_cells", -1), ("contributed_cells", 1.2),
    ("contributed_cells", "1"), ("name", ""), ("sha256", "f" * 63),
    ("sha256", "G" * 64), ("source_url", "javascript:alert(1)"),
    ("source_url", "https://user:pass@example.org/"),
    ("source_url", "https://example.org/\nfoo"),
])
def test_invalid_source_metadata_fails_closed(manifest, field, value):
    manifest["sources"][0][field] = value
    with pytest.raises(ValueError):
        render_manifest(manifest)


@pytest.mark.parametrize("field,value", [
    ("license", ""), ("terms_url", "http://example.org/"),
    ("attribution", None), ("csumb_involved", "false"),
    ("csumb_involved", None),
])
def test_missing_rights_never_silently_disappears(manifest, field, value):
    manifest["sources"][0]["rights"][field] = value
    with pytest.raises(ValueError):
        render_manifest(manifest)


@pytest.mark.parametrize("mutation", ["duplicate", "no-rights", "no-usage", "version", "sources"])
def test_invalid_contract(manifest, mutation):
    if mutation == "duplicate":
        manifest["sources"].append(deepcopy(manifest["sources"][0]))
    elif mutation == "no-rights":
        del manifest["sources"][0]["rights"]
    elif mutation == "no-usage":
        del manifest["sources"][0]["contributed_cells"]
    elif mutation == "version":
        manifest["schema_version"] = True
    else:
        manifest["sources"] = {}
    with pytest.raises(ValueError):
        render_manifest(manifest)


def test_csumb_flag_survives_cc0_label_and_incorrect_boolean(manifest):
    row = manifest["sources"][0]
    row["rights"]["license"] = "CC0-1.0"
    row["rights"]["csumb_involved"] = False
    page = render_manifest(manifest)
    assert "needs_permission" in page
    assert "A public-domain or CC0 release label does not resolve" in page


def test_html_is_escaped(manifest):
    manifest["sources"][0]["name"] = '<script>alert("x")</script>'
    manifest["sources"][0]["rights"]["attribution"] = '<img src=x onerror="x">'
    manifest["sources"][0]["source_url"] = 'https://example.org/?q="x"&a=1'
    page = render_manifest(manifest)
    parsed = Page()
    parsed.feed(page)
    assert "script" not in parsed.tags
    assert "img" not in parsed.tags
    assert '&lt;script&gt;' in page
    assert '&quot;x&quot;&amp;a=1' in page


def test_empty_manifest_keeps_disclaimer():
    page = render_manifest({"schema_version": 1, "sources": []})
    assert "No sources contributed" in page
    assert "Not for navigation" in page
    assert "review_required" in page


def test_cli_builds_fixture_page_and_pins_exact_input_bytes(tmp_path):
    output = tmp_path / "preview/rights.html"
    result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(FIXTURE),
                             "--output", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "review_required; not for navigation" in result.stdout
    first = output.read_bytes()
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest().encode() in first
    again = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(FIXTURE),
                            "--output", str(output)], capture_output=True, text=True)
    assert again.returncode == 0
    assert output.read_bytes() == first
    assert not list(output.parent.glob(".coast-rights-*"))


def test_cli_rejects_invalid_manifest_without_replacing_previous_output(tmp_path):
    manifest = tmp_path / "invalid.json"
    manifest.write_text('{"schema_version": 1, "sources": [{"source_id": "missing-usage"}]}')
    output = tmp_path / "rights.html"
    output.write_text("previous valid output")
    result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest),
                             "--output", str(output)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "contributed_cells" in result.stderr
    assert output.read_text() == "previous valid output"


def test_cli_refuses_input_overwrite(tmp_path):
    source = tmp_path / "manifest.json"
    source.write_bytes(FIXTURE.read_bytes())
    result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(source),
                             "--output", str(source)], capture_output=True, text=True)
    assert result.returncode == 2
    assert source.read_bytes() == FIXTURE.read_bytes()
