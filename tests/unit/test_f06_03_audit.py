"""F06-03 / SCA-216: the private terrain inspector must not call synthetic terrain a measured sample.

Contract: the visible heading names synthetic fixtures as "Synthetic test terrain — not survey
measurements"; the measured wording appears only when the accepted input is positively real
(`synthetic is False`); the private-use warnings stay.
Bug caught: a constant BODY heading that gives synthetic and real payloads the same measured claim.
The governed batch builds its inspector through this same `html()` with `metadata.acceptance` taken
from the receipt, so it inherits the label (verified with a numpy-backed run outside this non-GIS
layer). Offline, tiny in-memory payloads; no GIS stack.
"""
import pytest

from skippercast.coastal.render import terrain_demo as demo

SYNTHETIC = "Synthetic test terrain — not survey measurements"
MEASURED = "measured sample tile"
WARNINGS = ("INTERNAL DIAGNOSTIC · NOT FOR NAVIGATION · PUBLICATION PROHIBITED", "WEBSITE HELD · HABITAT UNASSESSED")


def _payload(**acceptance):
    return dict(schema=demo.SCHEMA, vertices=[[0, 0, -1]], faces=[], metadata=dict(acceptance=acceptance))


def _text(data):
    return demo.html(data).decode()


def _heading(page):
    start = page.index('<div class="map-title">')
    return page[start:page.index("</div>", start)]


def test_negative_control_synthetic_payload_is_labelled_synthetic():
    page = _text(_payload(synthetic=True))
    assert SYNTHETIC in _heading(page)
    assert MEASURED not in page
    assert all(w in page for w in WARNINGS)


def test_valid_control_real_payload_keeps_measured_wording():
    page = _text(_payload(synthetic=False))
    assert MEASURED in _heading(page) and "Synthetic test terrain" not in page
    assert all(w in page for w in WARNINGS)


@pytest.mark.parametrize("data", [_payload(), _payload(synthetic="false"), _payload(synthetic=None), {}, dict(metadata=None)])
def test_unknown_provenance_never_gets_measured_wording(data):
    page = _text(data)
    assert MEASURED not in page and "not survey measurements" in _heading(page)
