from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from skippercast.pipeline import chl_edges_feed, chl_edges_region


NOW = datetime(2026, 11, 18, 13, tzinfo=timezone.utc)
OBSERVED = "2026-11-18T12:00:00Z"
PRODUCT = "Fixture satellite"
CREDIT = "Fixture credit"
LAYER = "chlorophyll-observation"
TILE = f"habitat-tiles/{LAYER}-01.json"
MANIFEST = "habitat-dynamics.json"
OUTPUT = "chl-edges.json"
PRIOR = b'{ "prior": true }\n'


def _tile(when: str = OBSERVED) -> dict:
    return {
        "fields": ["latitude", "longitude", "chlorophyll_mg_m3"],
        "resolution_degrees": [0.25, 0.25],
        "frames": [{"time": when, "cells": [[36, -124, 1]]}],
    }


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _expected(region: Path, *, age: float = 24, observed_at: str | None = OBSERVED,
              fraction: float | None = None, withheld: str | None = None, stale: int = 0) -> dict:
    return {
        "schema_version": 1,
        "region_id": region.name,
        "layer_id": "chl-edges",
        "product": PRODUCT,
        "credit": CREDIT,
        "generated_at": "2026-11-18T13:00:00Z",
        "max_age_hours": age,
        "observed_at": observed_at,
        "observed_fraction": fraction,
        "withheld": withheld,
        "refused_frames": {"missing_time": 0, "unparseable_time": 0, "future": 0, "stale": stale},
        "edges": [],
    }


def test_c1_fresh_tiles_and_manifest(tmp_path: Path):
    """C1: Catch wrong tile order/filter, lost frame metadata, or writing outside the region."""
    region = tmp_path / "fixture-region"
    older = _tile("2026-11-18T11:00:00Z")
    fresh = _tile()
    second = f"{LAYER}-02.json"
    _write(region / "habitat-tiles" / second, fresh)
    _write(region / TILE, older)
    (region / "habitat-tiles/sst-analysis-01.json").write_bytes(b"not JSON")
    (region / f"habitat-tiles/{LAYER}-03.json").mkdir()
    meta = [{"time": OBSERVED, "valid_cells": 2, "total_cells": 5}]
    _write(region / MANIFEST, {"layers": {LAYER: {"frames": meta}}})
    (region / OUTPUT).write_bytes(PRIOR)

    with patch.object(chl_edges_feed, "publish", wraps=chl_edges_feed.publish) as publish:
        result = chl_edges_region.publish_region(str(region), NOW, 24, PRODUCT, CREDIT)
    publish.assert_called_once_with(
        "fixture-region", [(Path(TILE).name, older), (second, fresh)], meta, NOW, 24, PRODUCT, CREDIT,
    )
    expected = _expected(region, fraction=0.4)
    assert result == expected
    assert json.loads((region / OUTPUT).read_bytes()) == expected


def test_c1_stale_tiles_write_withheld_document(tmp_path: Path):
    """C1: Stale-only inputs must write the withheld feed rather than omit it or use old data."""
    _write(tmp_path / TILE, _tile("2026-11-16T12:00:00Z"))
    _write(tmp_path / MANIFEST, {"layers": {LAYER: {"frames": []}}})
    result = chl_edges_region.publish_region(tmp_path, NOW, 24, PRODUCT, CREDIT)
    expected = _expected(tmp_path, observed_at=None, withheld="no-usable-frame", stale=1)
    assert result == expected
    assert json.loads((tmp_path / OUTPUT).read_bytes()) == expected


@pytest.mark.parametrize("manifest", [None, {}, {"layers": {"sst-analysis": {"frames": []}}}],
                         ids=["no-file", "no-layers-key", "other-layer-only"])
def test_c1_missing_manifest_or_layer(tmp_path: Path, manifest: dict | None):
    """C1: Missing metadata must not prevent a fresh tile from producing a feed."""
    _write(tmp_path / TILE, _tile())
    if manifest is not None:
        _write(tmp_path / MANIFEST, manifest)
    result = chl_edges_region.publish_region(tmp_path, NOW, 24, PRODUCT, CREDIT)
    expected = _expected(tmp_path)
    assert result == expected
    assert json.loads((tmp_path / OUTPUT).read_bytes()) == expected


@pytest.fixture(params=[False, True], ids=["no-prior-feed", "prior-feed"])
def prior_feed(tmp_path: Path, request: pytest.FixtureRequest) -> bytes | None:
    if request.param:
        (tmp_path / OUTPUT).write_bytes(PRIOR)
        return PRIOR
    return None


def _assert_untouched(folder: Path, prior_feed: bytes | None) -> None:
    output = folder / OUTPUT
    if prior_feed is None:
        assert not output.exists()
    else:
        assert output.read_bytes() == prior_feed


@pytest.mark.parametrize("relative", [f"habitat-tiles/{LAYER}-02.json", MANIFEST], ids=["tile", "manifest"])
@pytest.mark.parametrize("invalid", [b"{", b"\xff", b'{"invalid": NaN}'], ids=["syntax", "utf8", "constant"])
def test_c2_invalid_json_names_file_and_leaves_output_untouched(
    tmp_path: Path, prior_feed: bytes | None, relative: str, invalid: bytes,
):
    """C2: A late bad tile or a bad manifest must not publish from partial inputs."""
    _write(tmp_path / TILE, _tile())
    bad = tmp_path / relative
    bad.write_bytes(invalid)
    before = sorted(tmp_path.iterdir())
    with pytest.raises(chl_edges_region.ChlEdgesRegionError) as exc:
        chl_edges_region.publish_region(tmp_path, NOW, 24, PRODUCT, CREDIT)
    assert exc.type is chl_edges_region.ChlEdgesRegionError
    assert str(exc.value).startswith(f"{bad}:")
    _assert_untouched(tmp_path, prior_feed)
    assert sorted(tmp_path.iterdir()) == before


def test_c2_feed_error_propagates_without_writing(tmp_path: Path, prior_feed: bytes | None):
    """C2: Valid JSON with invalid frame metadata must not be treated as a missing layer."""
    _write(tmp_path / TILE, _tile())
    _write(tmp_path / MANIFEST, {"layers": {LAYER: {"frames": None}}})
    with pytest.raises(chl_edges_feed.ChlEdgeFeedError, match="^frames_meta must be a list$") as exc:
        chl_edges_region.publish_region(tmp_path, NOW, 24, PRODUCT, CREDIT)
    assert exc.type is chl_edges_feed.ChlEdgeFeedError
    _assert_untouched(tmp_path, prior_feed)


def test_c2_failed_atomic_replace_leaves_output_untouched(
    tmp_path: Path, prior_feed: bytes | None, monkeypatch: pytest.MonkeyPatch,
):
    """C2: A failure at rename must not leave a partial feed or a temporary publication."""
    before = sorted(tmp_path.iterdir())
    failure = PermissionError("fixture refused replace")

    def fail_replace(self: Path, target: Path) -> Path:
        assert target == tmp_path / OUTPUT
        raise failure

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError) as exc:
        chl_edges_region.publish_region(tmp_path, NOW, 24, PRODUCT, CREDIT)
    assert exc.type is PermissionError
    assert exc.value is failure
    _assert_untouched(tmp_path, prior_feed)
    assert sorted(tmp_path.iterdir()) == before


def _cli_args(path: Path) -> list[str]:
    return ["--region-dir", str(path), "--max-age-hours", "1.5", "--product", PRODUCT, "--credit", CREDIT]


def test_c3_cli_publishes_with_utc_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """C3: Catch local-time clocks, truncated fractional ages and dropped CLI arguments."""
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None) -> datetime:
            assert tz is timezone.utc
            return NOW

    monkeypatch.setattr(chl_edges_region, "datetime", FrozenDatetime)
    monkeypatch.setattr(sys, "argv", ["chl_edges_region", *_cli_args(tmp_path)])
    _write(tmp_path / TILE, _tile("2026-11-18T11:45:00Z"))
    result = chl_edges_region.main()
    assert result == 0
    assert json.loads((tmp_path / OUTPUT).read_bytes()) == _expected(
        tmp_path, age=1.5, observed_at="2026-11-18T11:45:00Z",
    )


@pytest.mark.parametrize("option", ["--region-dir", "--max-age-hours", "--product", "--credit", "bad-age"])
def test_c3_cli_argparse_refusals_do_not_publish(tmp_path: Path, option: str):
    """C3: Omitted required arguments and an unparseable age must exit before writing."""
    args = _cli_args(tmp_path)
    if option == "bad-age":
        args[args.index("--max-age-hours") + 1] = "nope"
    else:
        start = args.index(option)
        del args[start:start + 2]
    with pytest.raises(SystemExit) as exc:
        chl_edges_region.main(args)
    assert exc.type is SystemExit
    assert exc.value.code == 2
    assert not (tmp_path / OUTPUT).exists()


def test_c3_cli_help_exits_without_publishing(tmp_path: Path):
    """C3: Asking for help must short-circuit publication without requiring other arguments."""
    with pytest.raises(SystemExit) as exc:
        chl_edges_region.main(["--region-dir", str(tmp_path), "--help"])
    assert exc.type is SystemExit
    assert exc.value.code == 0
    assert not (tmp_path / OUTPUT).exists()
