"""F06-03 / SCA-216: the private terrain inspector must not present synthetic terrain as measured.

Contract: a synthetic fixture renders the heading "Synthetic test terrain — not survey measurements";
the measured wording (heading, explanatory copy, mode label) appears only for an input that is both
`synthetic is False` AND confirmed reviewed (`metadata.review_confirmed`, set by `payload()` after it
re-reads the hash-bound independent review, or by the governed batch after `terrain.verify`).
A bare `synthetic=False`, an absent flag or an unreviewed claim gets the neutral label and copy. The
private-use warnings stay on every page. The governed batch builds its inspector through this same
`html()`, so it inherits all of this.
Bugs caught: constant BODY giving synthetic and real inputs the same measured claim; a bare
synthetic=False flag (no evidence of review) earning measured wording; measured-data sentences
surviving in the body/mode label after only the heading changed; a review that is not bound to this
acceptance, is itself synthetic, is self-review or carries holds being accepted as evidence.
Offline, tiny in-memory payloads and a tmp_path review file; no GIS stack.
"""
import hashlib
import json

import pytest

from skippercast.coastal.render import terrain_demo as demo

SYNTHETIC = "Synthetic test terrain — not survey measurements"
WARNINGS = ("INTERNAL DIAGNOSTIC · NOT FOR NAVIGATION · PUBLICATION PROHIBITED", "WEBSITE HELD · HABITAT UNASSESSED")
# Every measured-data claim the page body/script can show; none may appear for a non-real input.
CLAIMS = ("measured sample tile", "Accepted mesh", "accepted depth mesh", "between measured samples",
          "Measured mode", "original measured triangles", ">Measured<")
REVIEW = "coastal-terrain-only-science-review-v1"


def _payload(confirmed=False, **acceptance):
    return dict(schema=demo.SCHEMA, vertices=[[0, 0, -1]], faces=[],
                metadata=dict(acceptance=acceptance, review_confirmed=confirmed))


def _text(data):
    return demo.html(data).decode()


def _heading(page):
    start = page.index('<div class="map-title">')
    return page[start:page.index("</div>", start)]


def _assert_no_measured_claim(page):
    assert [claim for claim in CLAIMS if claim in page] == []
    assert all(w in page for w in WARNINGS)


def test_negative_control_synthetic_payload_is_labelled_synthetic_everywhere():
    page = _text(_payload(True, synthetic=True))
    assert SYNTHETIC in _heading(page)
    _assert_no_measured_claim(page)


def test_valid_control_reviewed_real_payload_keeps_measured_wording():
    page = _text(_payload(True, synthetic=False))
    assert "measured sample tile" in _heading(page) and "Synthetic test terrain" not in page
    assert all(claim in page for claim in ("between measured samples", "Measured mode", ">Measured<"))
    assert all(w in page for w in WARNINGS)


def test_negative_control_synthetic_flag_alone_is_not_review_evidence():
    page = _text(_payload(False, synthetic=False))
    assert "not survey measurements" in _heading(page)
    _assert_no_measured_claim(page)


@pytest.mark.parametrize("data", [_payload(synthetic=True), _payload(), _payload(synthetic="false"), _payload(synthetic=None),
                                  _payload(True, synthetic="false"), _payload(True), {}, dict(metadata=None),
                                  dict(metadata=dict(acceptance=dict(synthetic=False), review_confirmed="yes"))])
def test_unknown_or_unreviewed_provenance_never_gets_measured_wording(data):
    page = _text(data)
    assert "not survey measurements" in _heading(page)
    _assert_no_measured_claim(page)


def _acceptance(tmp_path, review=None, **changes):
    document = dict(schema=REVIEW, scope="internal-terrain-only-scientific-review", facts_digest="a" * 64,
                    independent=True, reviewer_id="reviewer-1", decision="accept", holds_added=[], synthetic=False)
    document.update(review or {})
    data = json.dumps(document).encode()
    (tmp_path / "review.json").write_bytes(data)
    reference = dict(path="review.json", bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), contract=REVIEW)
    return dict(synthetic=False, creator_id="creator-1", scientific_review=reference, **changes)


def _confirmed(tmp_path, acceptance):
    return demo._review_confirmed(tmp_path, dict(acceptance_context_sha256="a" * 64), acceptance)


def test_review_confirmed_positive_control(tmp_path):
    assert _confirmed(tmp_path, _acceptance(tmp_path)) is True


@pytest.mark.parametrize("review", [dict(facts_digest="b" * 64), dict(synthetic=True), dict(reviewer_id="creator-1"),
                                    dict(independent=False), dict(decision="reject"), dict(holds_added=["x"]),
                                    dict(scope="other"), dict(schema="other")])
def test_review_confirmed_refuses_unbound_synthetic_self_or_held_review(tmp_path, review):
    assert _confirmed(tmp_path, _acceptance(tmp_path, review)) is False


def test_review_confirmed_refuses_missing_tampered_or_synthetic_acceptance(tmp_path):
    good = _acceptance(tmp_path)
    assert _confirmed(tmp_path, {k: v for k, v in good.items() if k != "scientific_review"}) is False
    assert _confirmed(tmp_path, dict(good, synthetic=True)) is False
    (tmp_path / "review.json").write_bytes(b'{"decision":"accept"}' + b" " * (good["scientific_review"]["bytes"] - 21))
    assert _confirmed(tmp_path, good) is False
    (tmp_path / "review.json").unlink()
    assert _confirmed(tmp_path, good) is False
