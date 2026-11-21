import hashlib
import io

import pytest


@pytest.mark.gis
@pytest.mark.parametrize("case", ["short", "wrong-hash", "disconnect", "oversized", "valid"])
def test_coned_refresh_only_installs_verified_bytes(tmp_path, monkeypatch, case):
    from research.scripts import audit_monterey_coned_source_footprints as audit

    verified = b"synthetic verified package"
    previous = b"stale package" if case == "valid" else verified
    source = tmp_path / "source.gpkg"
    source.write_bytes(previous)
    monkeypatch.setattr(audit, "SOURCE_SIZE", len(verified), raising=False)
    monkeypatch.setattr(audit, "SHA256", hashlib.sha256(verified).hexdigest())
    body = {
        "short": verified[:-1],
        "wrong-hash": verified[:-1] + b"!",
        "disconnect": verified,
        "oversized": verified + b"!",
        "valid": verified,
    }[case]

    class Response(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            # Catch truncation before EOF, not just the final state after a rollback.
            assert source.read_bytes() == previous
            if case == "disconnect" and self.tell():
                raise ConnectionResetError("synthetic disconnect")
            return super().read(8 if size is None or size < 0 else min(size, 8))

    monkeypatch.setattr(audit, "urlopen", lambda *args, **kwargs: Response(body))
    if case == "valid":
        audit.verified_source(source, fetch=True)
        assert source.read_bytes() == verified
    else:
        error = ConnectionResetError if case == "disconnect" else ValueError
        with pytest.raises(error):
            audit.verified_source(source, fetch=True)
        assert source.read_bytes() == previous
    assert set(tmp_path.iterdir()) == {source}
    audit.verified_source(source, fetch=False)
