"""Synthetic transfer controls for the Point Conception originals cache."""
import hashlib
from io import BytesIO
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gis
PAYLOAD = b"reviewed original"
URL = "https://example.invalid/original"


@pytest.fixture(params=["interrupted", "short", "wrong-byte", "oversized"])
def transfer(request):
    fault = request.param
    first = {"interrupted": PAYLOAD, "short": PAYLOAD[:-1],
             "wrong-byte": b"!" + PAYLOAD[1:], "oversized": PAYLOAD + b"!"}[fault]
    # Let the oversized payload match the digest, so SHA-256 cannot mask a missing cap.
    expected = hashlib.sha256(first if fault == "oversized" else PAYLOAD).hexdigest()
    return fault, first, expected


@pytest.fixture(params=["bag", "noaa-report", "usgs-report"])
def cache_input(request, tmp_path, monkeypatch, transfer):
    fault, _, expected = transfer
    if request.param == "bag":
        from research.scripts import audit_point_conception_original_300_gap as gap

        path = tmp_path / "fixture.bag"
        if fault == "oversized":
            monkeypatch.setattr(gap, "ORIGINAL_MAX_BYTES", len(PAYLOAD))
        return gap, path, lambda: gap.fetch(path, URL, expected)

    from research.scripts import audit_point_conception_4m_lineage as lineage

    if request.param == "noaa-report":
        monkeypatch.setattr(lineage, "REPORT_HASHES", {"fixture": expected})
        if fault == "oversized":
            monkeypatch.setattr(lineage, "NOAA_REPORT_MAX_BYTES", len(PAYLOAD))
        path = tmp_path / "fixture-DR.pdf"
        return lineage, path, lambda: lineage.report_path(tmp_path, "fixture", fetch=True)

    monkeypatch.setattr(lineage, "USGS_PAMPHLET_SHA", expected)
    if fault == "oversized":
        monkeypatch.setattr(lineage, "USGS_REPORT_MAX_BYTES", len(PAYLOAD))
    path = tmp_path / "fixture.pdf"

    class Page:
        def extract_text(self):
            return "Bathymetry and backscatter data collected by Fugro Pelagos in 2008"

    monkeypatch.setattr(lineage, "PdfReader", lambda _: SimpleNamespace(pages=[Page()]))
    return lineage, path, lambda: lineage.usgs_acoustic_source(path, fetch=True)


def test_only_verified_bytes_enter_cache(cache_input, monkeypatch, transfer):
    # Direct writes strand the next explicit fetch; early promotion exposes partial bytes.
    module, path, fetch = cache_input
    fault, bad, _ = transfer
    calls = []

    class Stream(BytesIO):
        url: str
        headers: dict[str, str]

        def read(self, size=-1, /):
            assert not path.exists(), "unverified bytes became visible at the final path"
            if len(calls) == 1 and fault == "interrupted":
                if self.tell():
                    raise OSError("synthetic interruption")
                size = 1
            return super().read(size)

    def open_stream(request, *, timeout):
        calls.append(request)
        assert len(calls) <= 2, "the caller, not the cache, authorizes each attempt"
        stream = Stream(bad if len(calls) == 1 else PAYLOAD)
        stream.url = request if isinstance(request, str) else request.full_url
        stream.headers = {} if fault == "oversized" else {"Content-Length": str(len(PAYLOAD))}
        return stream

    monkeypatch.setattr(module, "urlopen", open_stream)

    error = OSError if fault == "interrupted" else ValueError
    with pytest.raises(error):
        fetch()
    assert len(calls) == 1
    assert not path.exists()
    assert not list(path.parent.iterdir())
    if fault == "oversized":
        return
    fetch()
    assert len(calls) == 2
    assert path.read_bytes() == PAYLOAD
    before = path.stat()
    fetch()
    assert len(calls) == 2
    after = path.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert path.read_bytes() == PAYLOAD
    assert list(path.parent.iterdir()) == [path]


def test_bag_install_does_not_replace_a_concurrent_valid_original(tmp_path, monkeypatch):
    # A verified temp file followed by unconditional replace would still clobber a winner.
    from research.scripts import audit_point_conception_original_300_gap as gap

    path = tmp_path / "fixture.bag"
    winner = tmp_path / "winner"
    winner.write_bytes(PAYLOAD)

    class Stream(BytesIO):
        headers = {"Content-Length": str(len(PAYLOAD))}

        def __exit__(self, *exc):
            path.hardlink_to(winner)
            return super().__exit__(*exc)

    monkeypatch.setattr(gap, "urlopen", lambda *_args, **_kwargs: Stream(PAYLOAD))
    gap.fetch(path, URL, hashlib.sha256(PAYLOAD).hexdigest())
    assert path.samefile(winner)
    assert path.read_bytes() == PAYLOAD
