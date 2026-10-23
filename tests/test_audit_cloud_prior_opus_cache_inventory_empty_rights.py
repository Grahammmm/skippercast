"""Audit repro: an empty rights/header/scope metadata document clears every hold.

cached_inventory.inventory() gates rights, vertical datum and scope review with
`if rights and (...)`, `if header:` and `if scope and (...)`. A descriptor that is
present (so no *_metadata_missing hold) but whose hash-pinned JSON is `{}` is
falsy, so no rights/datum/scope hold is added and the source is reported
usable_for_acquisition_request=True.
"""
import hashlib

from skippercast.coastal import cached_inventory as ci


def _descriptor(path, contract="cached-source-json-v1"):
    data = path.read_bytes()
    return dict(path=path.name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), contract=contract)


def _write(path, value):
    path.write_bytes(ci.encoded(value))
    return _descriptor(path)


def test_empty_rights_header_scope_documents_do_not_clear_holds(tmp_path):
    source = dict(sha256="a" * 64, bytes=4, url="https://example.org/source.bag")
    (tmp_path / "source.bag").write_bytes(b"data")
    candidate = dict(
        source_manifest=_write(tmp_path / "source.json", source),
        prepared_acquisition=_write(tmp_path / "prepared.json", dict(source=dict(sha256="a" * 64, bytes=4))),
        header=_write(tmp_path / "header.json", {}),
        rights=_write(tmp_path / "rights.json", {}),
        scope=_write(tmp_path / "scope.json", {}),
        cache_path="source.bag", window_set=[[0, 0, 4, 4]])
    plan = dict(schema=ci.PLAN, region="synthetic", candidates=[candidate],
                metadata_bytes=ci.MAX_METADATA, output_bytes=ci.MAX_OUTPUT,
                network_bytes=0, source_read_bytes=0, output_root=str(tmp_path / "output"))
    result = ci.inventory(tmp_path, plan, now=100, horizon=200)
    entry = result["sources"][0]
    # Correct behaviour: an empty rights document is not an accepted rights review.
    assert "private_source_rights_unreviewed" in entry["holds"]
    assert entry["usable_for_acquisition_request"] is False
    assert result["usable_source_ids"] == []


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)
