"""Offline runtime checks for the generated depth-confidence explanation."""
import json
import re

import pytest

from scripts import build_sources_register as register
from tests._support import ROOT
from tests.unit.test_sources_register import BOUND_SOURCE, make_root, region, row


SOURCE_NAME = 'Fixture Credit Name'
SECTION = rb'        <section id="depth-confidence">\n.*?</section>\n'
# Output of the pre-change generator for this synthetic input, including the credits and page shell.
BASELINE = '''<main id="sources-content">
      <h1>Sources</h1>
      <p>Hand-written method text stays.</p>
      <!-- BEGIN GENERATED data-sources: scripts/build_sources_register.py (do not edit by hand) -->
      <section id="data-sources" aria-labelledby="data-sources-heading">
        <h2 id="data-sources-heading">Data sources register</h2>
        <p>This list is generated from the reviewed source register, with each credit as the register records it. The map itself shows no source names; its measured, estimated and unsurveyed labels describe data quality and stay as they are. Eligibility for public display is a rights decision that does not release a layer.</p>
        <p>1 sources are in use on live layers; 0 more are eligible for public display but no layer uses them yet.</p>
        <h3 id="data-sources-live">In use on live layers</h3>
        <h4 id="region-r1">Fixture Bay</h4>
        <h5>Protected areas</h5>
        <ul>
          <li><strong>Fixture Credit Name</strong> · Agency cdfw-mpas<br />
            Provides: Seabed depth and relief<br />
            Credit: Credit for cdfw-mpas · <a href="https://example.org/cdfw-mpas/about" rel="noopener" aria-label="Fixture Credit Name: source page">Source page</a></li>
        </ul>
        <h3 id="data-sources-eligible">Eligible for public display, not yet used</h3>
        <p>No source is waiting; every eligible source is in use.</p>
      </section>
      <!-- END GENERATED data-sources -->
      <h2>Current official checks</h2>
      <ul><li><a href="https://example.org/">Official</a></li></ul>
    </main>
'''.encode('utf-8')


@pytest.fixture
def fixture_root(tmp_path):
    return make_root(tmp_path, [row(BOUND_SOURCE, SOURCE_NAME)],
                     [region('r1', 'Fixture Bay', bound=True)], stub=BASELINE.decode('utf-8'))


def test_c1_explains_the_exact_map_labels(fixture_root):
    """C1: A missing item, a rephrased label, or a claim that all fine grids are measured is misleading."""
    assert register.main(['--root', str(fixture_root)]) == 0
    page = (fixture_root / 'dist/sources.html').read_bytes()
    section, = re.findall(SECTION, page, re.S)
    text = section.decode('utf-8')

    detail = (ROOT / 'web/map/survey-detail.ts').read_text(encoding='utf-8')
    measured, = re.findall(r'const measuredLabel = \{([^}]+)\}', detail)
    labels = dict(re.findall(r"'([^']+)': '([^']+)'", measured))
    fine, medium, coarse = (labels[tier] for tier in ('1m-measured', '2m', '5m'))
    estimated, = re.findall(r"if \(p\.tier === 'estimated'\) return `([^`]+)`", detail)
    estimated_example = estimated.replace('${p.grid_m}', '8')
    legend = (ROOT / 'web/map/legend-model.ts').read_text(encoding='utf-8')
    label_id, = re.findall(r'labelId: `([^`]+)`', legend)
    strings = json.loads((ROOT / 'catalog/app/strings.json').read_text(encoding='utf-8'))['strings']
    none = strings[label_id.replace('${id}', 'none')]['en']

    assert re.findall(r'<h[1-6]>([^<]+)</h[1-6]>', text) == ['Depth confidence']
    assert re.findall(r'<li>(.*?)</li>', text, re.S) == [
        f'<strong>{fine}</strong> applies only where a survey is certified for 1 m detail. '
        f'Other measured areas show the grid size, such as <strong>{medium}</strong> or <strong>{coarse}</strong>.',
        f'<strong>{estimated_example}</strong> means the depths come from a compiled grid. '
        'The number is the grid size in that area.',
        f'<strong>{none}</strong> means no survey data is available in this map area.',
    ]


def test_c2_check_rejects_a_missing_explanation_then_accepts_one_before_credits(fixture_root):
    """C2: Missing, duplicated, misplaced or source-specific copy makes the explanation unreliable."""
    root_args = ['--root', str(fixture_root)]
    assert register.main(['--check', *root_args]) == 1
    path = fixture_root / 'dist/sources.html'
    assert path.read_bytes() == BASELINE  # Check mode refuses to rewrite a stale page.
    assert register.main(root_args) == 0
    page = path.read_bytes()
    section, = re.findall(SECTION, page, re.S)
    assert page.count(b'id="depth-confidence"') == 1
    assert page.index(section) + len(section) <= page.index(b'<h4 id="region-r1">')
    assert BOUND_SOURCE.encode() not in section and SOURCE_NAME.encode() not in section
    assert b'<strong>Fixture Credit Name</strong>' in page  # The credit is still present elsewhere.
    assert register.main(['--check', *root_args]) == 0
    assert path.read_bytes() == page


def test_c3_regeneration_only_inserts_the_explanation(fixture_root):
    """C3: A rewrite to the credits or the surrounding page must not ride along with the new section."""
    assert register.main(['--root', str(fixture_root)]) == 0
    page = (fixture_root / 'dist/sources.html').read_bytes()
    remainder, count = re.subn(SECTION, b'', page, flags=re.S)
    assert (remainder, count) == (BASELINE, 1)
