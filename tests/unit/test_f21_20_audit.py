"""A verification receipt must not replace its own evidence archive."""

import hashlib
import json
import sys
import zipfile

import pytest

from scripts import verify_legal_review_artifact as verifier
from skippercast.pipeline.regulations import content_hash


@pytest.fixture
def archive(tmp_path, monkeypatch):
    jurisdiction = {"id": "test-coast"}
    source_id = "test-rules"
    source = {"url": "https://example.org/rules.pdf", "normalization": "pdf-bytes-v1"}
    registry = {"sources": {source_id: source}}
    body = b"%PDF-1.4 synthetic rules\n"
    packet = {
        "jurisdiction_id": jurisdiction["id"],
        "collected_at": "2026-09-24T14:00:00Z",
        "rules_content_sha256": content_hash(registry),
        "sources": {source_id: {"status": "ok", "url": source["url"], "data": {
            "normalization": source["normalization"], "content_sha256": hashlib.sha256(body).hexdigest(),
        }}},
    }
    monkeypatch.setattr(verifier, "jurisdiction_files", lambda _: (jurisdiction, registry, None))
    path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("packet.json", json.dumps(packet))
        zipped.writestr("coverage.json", json.dumps({"jurisdiction_id": jurisdiction["id"]}))
        zipped.writestr(f"{source_id}.pdf", body)
    return path


def run_cli(monkeypatch, archive, output):
    monkeypatch.setattr(sys, "argv", ["verify_legal_review_artifact.py", str(archive),
                                      "--jurisdiction", "test-coast", "--output", str(output)])
    verifier.main()


@pytest.mark.parametrize("alias", ["direct", "normalized", "missing-parent", "symlink", "hardlink"])
def test_cli_refuses_archive_as_receipt(archive, alias, monkeypatch, capsys):
    root = archive.parent
    if alias == "direct":
        output = archive
    elif alias in ("normalized", "missing-parent"):
        parent = root / "sub"
        if alias == "normalized":
            parent.mkdir()
        output = parent / ".." / archive.name
    else:
        output = root / "alias.zip"
        if alias == "symlink":
            output.symlink_to(archive.name)
        else:
            output.hardlink_to(archive)
    original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    original_entries = sorted(root.iterdir())

    # A valid packet used to reach os.replace even with its own path as --output.
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, archive, output)
    assert stopped.value.code == 1
    stdout, stderr = capsys.readouterr()
    assert not stdout
    assert stderr == "Legal review artifact refused: output must not name the input archive\n"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original_hash
    assert sorted(root.iterdir()) == original_entries
    if alias != "missing-parent":
        assert output.samefile(archive)


def test_cli_creates_receipt_at_distinct_path(archive, monkeypatch, capsys):
    output = archive.parent / "receipts" / "verification.json"
    original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    run_cli(monkeypatch, archive, output)
    stdout, stderr = capsys.readouterr()
    assert not stderr
    receipt = json.loads(output.read_text())
    assert receipt == json.loads(stdout)
    assert receipt["archive_sha256"] == original_hash
    assert receipt["source_ids"] == ["test-rules"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original_hash
