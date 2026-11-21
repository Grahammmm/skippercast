import hashlib
import json
import os
from pathlib import Path
from typing import cast

import pytest

from skippercast.pipeline.habitat_dynamics import publish_tiles
from skippercast.pipeline.habitat_history_tiles import history_tile, prune_history, write_history_tile

_FIRST = 1704067199  # 2023-12-31 23:59:59 UTC
_SECOND = 1704067200
_BOUNDS = [-1.0, 1.0, -0.5, 1.5]
_PREFIX = (
    b'{"schema_version":1,"region_id":"test-coast","layer_id":"sst-analysis",'
    b'"bounds":[-1.0,1.0,-0.5,1.5],"resolution_degrees":[0.25,0.25],'
    b'"fields":["latitude","longitude","temperature_c","analysis_error_c"],"frames":['
)
_FIRST_BYTES = _PREFIX + b'{"time":1704067199,"cells":[[1,-1,12.5,null]],"valid_cells":1}]}\n'
_SECOND_BYTES = _PREFIX + b'{"time":1704067200,"cells":[[1,-1,13.0,0.2]],"valid_cells":1}]}\n'


@pytest.fixture
def tile() -> dict:
    return {
        "schema_version": 1,
        "region_id": "test-coast",
        "layer_id": "sst-analysis",
        "bounds": _BOUNDS.copy(),
        "resolution_degrees": [0.25, 0.25],
        "fields": ["latitude", "longitude", "temperature_c", "analysis_error_c"],
        "frames": [
            {"time": _FIRST, "cells": [[1, -1, 12.5, None]], "valid_cells": 1},
            {"time": _SECOND, "cells": [[1, -1, 13.0, 0.2]], "valid_cells": 1},
        ],
    }


def _ref(data: bytes, day: str) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    return {
        "path": f"habitat-history/sst-analysis-{day}-{sha[:16]}.json",
        "sha256": sha,
        "bytes": len(data),
        "bounds": _BOUNDS,
    }


@pytest.mark.parametrize(("when", "day", "expected"), [
    (_FIRST, "20231231", _FIRST_BYTES),
    (_SECOND, "20240101", _SECOND_BYTES),
])
def test_c1_selects_each_frame_at_utc_day_boundary(tile: dict, when: int, day: str, expected: bytes):
    # Catch a changed encoding, a wrong frame/day, or an in-place frames replacement.
    original = json.dumps(tile)
    assert history_tile(tile, when) == (expected, _ref(expected, day))
    assert json.dumps(tile) == original


def test_c1_preserves_key_order_and_extra_metadata(tile: dict):
    # Catch reconstruction from a fixed list of publisher keys.
    reordered = {"frames": tile["frames"], **tile, "label": "café"}
    metadata, frame = _FIRST_BYTES.split(b'"frames":', 1)
    expected = b'{"frames":' + frame[:-2] + b"," + metadata[1:-1] + b',"label":"caf\\u00e9"}\n'
    assert history_tile(reordered, _FIRST) == (expected, _ref(expected, "20231231"))


@pytest.mark.parametrize("key", ["schema_version", "region_id", "layer_id", "bounds", "fields", "frames"])
def test_c2_missing_tile_key(tile: dict, key: str):
    del tile[key]
    with pytest.raises(ValueError, match=r"\Atile\Z", check=lambda e: type(e) is ValueError):
        history_tile(tile, _FIRST)


@pytest.mark.parametrize("change", [{"schema_version": 2}, {"layer_id": "sst/analysis"},
                                      {"layer_id": "sst-analysis\n"}, {"layer_id": 12}])
def test_c2_invalid_tile_value(tile: dict, change: dict):
    with pytest.raises(ValueError, match=r"\Atile\Z", check=lambda e: type(e) is ValueError):
        history_tile({**tile, **change}, _FIRST)


def test_c2_rejects_non_dict():
    with pytest.raises(ValueError, match=r"\Atile\Z", check=lambda e: type(e) is ValueError):
        history_tile(cast(dict, []), _FIRST)


@pytest.mark.parametrize("matches", [0, 2])
def test_c2_requires_exactly_one_match(tile: dict, matches: int):
    tile["frames"] = [tile["frames"][0]] * matches + [tile["frames"][1]]
    with pytest.raises(ValueError, match=r"\Aframe\Z", check=lambda e: type(e) is ValueError):
        history_tile(tile, _FIRST)


@pytest.mark.parametrize("when", [float(_FIRST), str(_FIRST), True, False])
def test_c2_rejects_non_integer_time_before_frame_lookup(tile: dict, when: object):
    with pytest.raises(ValueError, match=r"\Atime\Z", check=lambda e: type(e) is ValueError):
        history_tile(tile, cast(int, when))


def test_c3_writes_via_tmp_sibling(tmp_path: Path, tile: dict, monkeypatch: pytest.MonkeyPatch):
    ref = _ref(_FIRST_BYTES, "20231231")
    path = tmp_path / ref["path"]
    original_link = os.link
    publications = []

    def observe_link(source: Path, dest: Path) -> None:
        # Catch direct writes to the immutable path, including partial output before publication.
        publications.append((source.parent, source.suffix, dest, dest.exists(), source.read_bytes()))
        original_link(source, dest)

    monkeypatch.setattr(os, "link", observe_link)
    assert write_history_tile(tmp_path, tile, _FIRST) == ref
    assert publications == [(path.parent, ".tmp", path, False, _FIRST_BYTES)]
    assert path.read_bytes() == _FIRST_BYTES
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("existing", [_FIRST_BYTES, b"other bytes"])
def test_c3_concurrent_destination_is_never_overwritten(
    tmp_path: Path, tile: dict, monkeypatch: pytest.MonkeyPatch, existing: bytes,
):
    ref = _ref(_FIRST_BYTES, "20231231")
    path = tmp_path / ref["path"]
    original_exists = Path.exists
    created = []

    def race_exists(candidate: Path) -> bool:
        result = original_exists(candidate)
        if candidate == path and not result and not created:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(existing)
            created.append(candidate.stat())
        return result

    monkeypatch.setattr(Path, "exists", race_exists)
    if existing == _FIRST_BYTES:
        assert write_history_tile(tmp_path, tile, _FIRST) == ref
    else:
        with pytest.raises(ValueError, match=r"\Aimmutable\Z"):
            write_history_tile(tmp_path, tile, _FIRST)
    assert created
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == (
        existing, created[0].st_ino, created[0].st_mtime_ns,
    )
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("existing", [_FIRST_BYTES, b"other bytes"])
def test_c3_immutable_rewrite(tmp_path: Path, tile: dict, existing: bytes):
    ref = _ref(_FIRST_BYTES, "20231231")
    path = tmp_path / ref["path"]
    path.parent.mkdir()
    path.write_bytes(existing)
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    before = path.stat()
    if existing == _FIRST_BYTES:
        assert write_history_tile(tmp_path, tile, _FIRST) == ref
    else:
        with pytest.raises(ValueError, match=r"\Aimmutable\Z", check=lambda e: type(e) is ValueError):
            write_history_tile(tmp_path, tile, _FIRST)
    assert (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) == (
        existing, before.st_mtime_ns, before.st_ino,
    )
    assert list(path.parent.iterdir()) == [path]


def test_c4_prunes_only_unkept_history_names_in_sorted_order(tmp_path: Path):
    folder = tmp_path / "habitat-history"
    folder.mkdir()
    first = "sst-2-20231231-0123456789abcdef.json"
    second = "sst-2-20240101-0123456789abcdef.json"
    kept = "sst-2-20240102-0123456789abcdef.json"
    unmatched = ["manifest.json", "sst-2-2024-01-01-0123456789abcdef.json",
                 "sst-2-20240101-0123456789ABCDEF.json", "sst-2-20240101-0123456789abcdef.json\n",
                 "sst-2-20240101-0123456789abcdef.tmp"]
    subdir = folder / "sst-2-20240103-0123456789abcdef.json"
    subdir.mkdir()
    for name in [second, first, kept, *unmatched]:
        (folder / name).write_bytes(name.encode())
    assert prune_history(tmp_path, iter([f"habitat-history/{kept}"])) == [first, second]
    assert {path.name for path in folder.iterdir()} == {kept, *unmatched, subdir.name}
    assert {name: (folder / name).read_bytes() for name in [kept, *unmatched]} == {
        name: name.encode() for name in [kept, *unmatched]
    }
    assert list(subdir.iterdir()) == []


@pytest.mark.parametrize("bad_keep", ["habitat-history-other/file.json", "habitat-history/../file.json",
                                       "/habitat-history/file.json", "habitat-history/"])
def test_c4_bad_keep_does_not_prune_anything(tmp_path: Path, bad_keep: str):
    folder = tmp_path / "habitat-history"
    folder.mkdir()
    kept = "habitat-history/sst-20231231-0123456789abcdef.json"
    unkept = "habitat-history/sst-20240101-0123456789abcdef.json"
    for ref in (kept, unkept):
        (tmp_path / ref).write_bytes(ref.encode())
    with pytest.raises(ValueError, match=r"\Akeep\Z", check=lambda e: type(e) is ValueError):
        prune_history(tmp_path, iter([kept, bad_keep]))
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == {
        Path(ref).name: ref.encode() for ref in (kept, unkept)
    }


def test_c4_missing_history_folder_is_a_noop(tmp_path: Path):
    assert prune_history(tmp_path, []) == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("link_name", ["habitat-history", _ref(_FIRST_BYTES, "20231231")["path"]])
def test_c5_does_not_write_or_prune_through_symlinks(tmp_path: Path, tile: dict, link_name: str):
    target = tmp_path / "target"
    outside = tmp_path / "outside"
    outside.mkdir()
    basename = Path(_ref(_FIRST_BYTES, "20231231")["path"]).name
    sentinel = outside / basename
    sentinel.write_bytes(b"outside target")
    link = target / link_name
    link.parent.mkdir(parents=True)
    link.symlink_to(outside if link_name == "habitat-history" else sentinel)
    with pytest.raises(ValueError, match=r"\Aimmutable\Z", check=lambda e: type(e) is ValueError):
        write_history_tile(target, tile, _FIRST)
    assert prune_history(target, []) == []
    assert link.readlink() == (outside if link_name == "habitat-history" else sentinel)
    assert {p.name: p.read_bytes() for p in outside.iterdir()} == {basename: b"outside target"}


def test_c5_offline_publisher_to_history_with_negative_tile_index(tmp_path: Path, tile: dict):
    layer = {"id": tile["layer_id"], "resolution_degrees": tile["resolution_degrees"],
             "fields": tile["fields"], "frames": tile["frames"]}
    current = tmp_path / "current"
    past = tmp_path / "past"
    [published] = publish_tiles(layer, current, "test-coast")["tiles"]
    payload = (current / published["path"]).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert published == {"path": f"habitat-tiles/sst-analysis--2-2-{digest[:16]}.json",
                         "bounds": _BOUNDS, "sha256": digest, "bytes": len(payload)}
    ref = _ref(_SECOND_BYTES, "20240101")
    assert write_history_tile(past, json.loads(payload), _SECOND) == ref
    assert (past / ref["path"]).read_bytes() == _SECOND_BYTES
    assert (current / published["path"]).read_bytes() == payload
