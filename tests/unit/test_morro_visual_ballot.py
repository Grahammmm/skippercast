"""Contracts at the M28-to-ballot boundary (no screenshots or network required)."""
import hashlib
import itertools
import json

import pytest

from scripts.relief.morro_visual_ballot import render


@pytest.fixture
def packet(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    questions = {
        "GAP": {"camera": "gap", "allowed": ["yes", "no", "cannot-tell"], "text": "Gap <visible>?"},
        "LABEL": {"camera": "harbor", "allowed": ["yes", "no", "no-lines-visible", "cannot-tell"], "text": "Label?"},
    }
    pairs = []
    for i, (question, theme, zoom) in enumerate(itertools.product(questions, ("light", "dark"), (11, 13, 15)), 1):
        pid = f"pair-{i:02d}"
        pictures = {}
        for side in "AB":
            filename = f"images/{pid}-{side}.png"
            raw = b"\x89PNG\r\n\x1a\n" + filename.encode()
            (tmp_path / filename).write_bytes(raw)
            pictures[side] = {"file": filename, "sha256": hashlib.sha256(raw).hexdigest()}
        pairs.append(dict(pair=pid, question=question, theme=theme, zoom=zoom,
                          camera=questions[question]["camera"], images=pictures))
    doc = {"schema": "sc-morro-blind-pairs/1", "key_sha256": "a" * 64,
           "questions": questions, "pairs": pairs}
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(json.dumps(doc))
    return manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_ballot_renders_each_view_and_explicit_unknown_without_blind_key(packet):
    # Catch losing a side, making a decision the default, or disclosing the key.
    manifest, pin = packet
    page = render(manifest, pin)
    assert page.count('src="data:image/png;base64,') == 24
    assert page.count('<option value="">Unjudged</option>') == 24
    assert page.count('<option value="cannot-tell">') == 24
    assert page.count('<option value="no-lines-visible">') == 12
    assert "Gap &lt;visible&gt;?" in page and pin in page and "a" * 64 not in page


@pytest.mark.parametrize("changed, message", [("photo", "picture does not match"), ("camera", "manifest does not match")])
def test_ballot_refuses_swapped_bytes_or_relabelled_camera(packet, changed, message):
    # Catch checking only filenames or accepting a changed manifest's self-description.
    manifest, pin = packet
    if changed == "photo":
        path = manifest.parent / "images/pair-01-A.png"
        path.write_bytes(path.with_name("pair-01-B.png").read_bytes())
    else:
        manifest.write_text(manifest.read_text().replace('"camera": "gap"', '"camera": "harbor"'))
    with pytest.raises(ValueError, match=message):
        render(manifest, pin)
