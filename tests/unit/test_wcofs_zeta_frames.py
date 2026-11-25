"""Offline contract tests for reading WCOFS zeta frames through a client."""

from datetime import datetime, timezone

import pytest

from skippercast.pipeline.wcofs_ssh_layer import ssh_layer
from skippercast.pipeline.wcofs_zeta import WcofsZetaContractError
from skippercast.pipeline.wcofs_zeta_frames import WcofsZetaFramesError, zeta_frames


BASE = "https://fixture.invalid/dodsC/"
STEM = "wcofs.t00z.20260101.regulargrid"
F000, F003, F072 = (f"{STEM}.f{hour:03d}.nc" for hour in (0, 3, 72))
CYCLE = datetime(2026, 1, 1, tzinfo=timezone.utc)
ORIGIN = datetime(2025, 12, 31, 22, tzinfo=timezone.utc)
LAT = [35.0, 35.04]
LON = [-121.0, -120.96, -120.92]
DDS = """Dataset {
    Float32 Latitude[ny = 4][nx = 6];
    Float32 Longitude[ny = 4][nx = 6];
    Float32 zeta[time = 1][ny = 4][nx = 6];
    Float64 time[time = 1];
} frame.nc;"""
DAS = '''Attributes {
    zeta {
        String long_name "free-surface";
        String units "meters";
        Float32 _FillValue -9999;
    }
}'''
ASCII_QUERY = ".ascii?zeta%5B0%5D%5B2%3A1%3A3%5D%5B3%3A1%3A5%5D,time"


class Client:
    def __init__(self, first=F000, *, dds=DDS, das=DAS):
        self.metadata = [BASE + first + ".dds", BASE + first + ".das"]
        self.replies = dict(zip(self.metadata, (dds, das), strict=True))
        self.calls = []

    def get(self, url: str) -> str:
        self.calls.append(url)
        return self.replies[url]

    def add_frame(
        self, file: str, times: str | None,
        rows: str | None = "[0][0], 0.25, -9999, 0.75\n[0][1], 0.5, 0.5, 0.5",
    ) -> None:
        time_count = len(times.split(",")) if times else 1
        time_data = f"time[{time_count}]\n{times}" if times is not None else ""
        zeta_data = f"zeta[1][2][3]\n{rows}" if rows is not None else ""
        self.replies[BASE + file + ASCII_QUERY] = f"""Dataset {{
    Float32 zeta[time = 1][ny = 2][nx = 3];
    Float64 time[time = {time_count}];
}} frame.nc;
---------------------------------------------
{zeta_data}
{time_data}
"""


@pytest.mark.parametrize(("bounds", "latitudes", "longitudes"), [
    ((3, 4, 3, 5), LAT, LON),
    ((2, 3, 4, 6), LAT, LON),
    ((2, 3, 3, 5), LAT[:1], LON),
    ((2, 3, 3, 5), LAT, LON + [-120.88]),
], ids=["ny-stop", "nx-stop", "short-latitudes", "long-longitudes"])
def test_c1_rejects_subset_before_dap(bounds: tuple[int, int, int, int], latitudes, longitudes):
    """C1: Catch inclusive-stop overflow or a coordinate count check dropped on either axis."""
    client = Client()
    with pytest.raises(WcofsZetaFramesError) as caught:
        y0, y1, x0, x1 = bounds
        zeta_frames(client, BASE, [F000], CYCLE, ORIGIN, 60, y0, y1, x0, x1, latitudes, longitudes)
    assert caught.type is WcofsZetaFramesError
    assert client.calls == client.metadata


@pytest.mark.parametrize(("dds", "das"), [
    (DDS.replace("zeta[", "temp["), DAS),
    (DDS, DAS.replace('"meters"', '"cm"')),
], ids=["wrong-dds", "wrong-das"])
def test_c1_contract_error_propagates(dds, das):
    """C1: Catch ignoring either metadata reply or wrapping the contract's error."""
    client = Client(dds=dds, das=das)
    with pytest.raises(WcofsZetaContractError) as caught:
        zeta_frames(client, BASE, [F000], CYCLE, ORIGIN, 60, 2, 3, 3, 5, LAT, LON)
    assert caught.type is WcofsZetaContractError
    assert client.calls == client.metadata


DECOYS = [f"{STEM}.{suffix}" for suffix in (
    "f075.nc", "f004.nc", "f-03.nc", "f03.nc", "f0000.nc", "f003.nc.bak", "n003.nc",
)]


@pytest.mark.parametrize("files", [[], DECOYS], ids=["empty", "no-matching-file"])
def test_c2_no_forecast_steps(files):
    """C2: Catch returning an empty list, indexing an empty input, or requesting a decoy."""
    client = Client(files[0] if files else F000)
    with pytest.raises(WcofsZetaFramesError) as caught:
        zeta_frames(client, BASE, files, CYCLE, ORIGIN, 60, 2, 3, 3, 5, LAT, LON)
    assert caught.type is WcofsZetaFramesError
    assert client.calls == (client.metadata if files else [])


def test_c2_invalid_indices_keep_query_error():
    """C2: Catch bypassing the existing query validation or sending a negative slice."""
    client = Client()
    with pytest.raises(WcofsZetaContractError) as caught:
        zeta_frames(client, BASE, [F000], CYCLE, ORIGIN, 60, -1, 0, 3, 5, LAT, LON)
    assert caught.type is WcofsZetaContractError
    assert client.calls == client.metadata


@pytest.mark.parametrize("times", [None, "", "18000, 18000"], ids=["absent", "empty", "multiple"])
def test_c2_requires_one_time_value(times):
    """C2: Catch leaking a missing-key error or consuming just the first time value."""
    client = Client(F003)
    client.add_frame(F003, times)
    with pytest.raises(WcofsZetaFramesError) as caught:
        zeta_frames(client, BASE, [F003], CYCLE, ORIGIN, 1, 2, 3, 3, 5, LAT, LON)
    assert caught.type is WcofsZetaFramesError
    assert client.calls == [*client.metadata, BASE + F003 + ASCII_QUERY]


@pytest.mark.parametrize("times", ["17939", "18060.25", "nan", "inf"], ids=["early", "late", "nan", "inf"])
def test_c2_refuses_time_outside_tolerance(times):
    """C2: Catch rounding before validation or reading the next step after a bad time."""
    client = Client(F072)
    client.add_frame(F003, times)
    with pytest.raises(WcofsZetaFramesError) as caught:
        zeta_frames(client, BASE, [F072, F003], CYCLE, ORIGIN, 1, 2, 3, 3, 5, LAT, LON)
    assert caught.type is WcofsZetaFramesError
    assert client.calls == [*client.metadata, BASE + F003 + ASCII_QUERY]


@pytest.mark.parametrize("rows", [
    None,
    "[0][0], 0.25, 0.5, 0.75\n[0][1], 0.5, 0.5",
    "[0][0], 0.25, 0.5, 0.75\n[0][1], 0.5, 0.5, 0.5, 0.5",
], ids=["missing", "short", "extra"])
def test_c2_wrong_cell_count_keeps_row_error(rows):
    """C2: Catch emitting an incomplete frame or dropping extra cells instead of refusing it."""
    client = Client()
    client.add_frame(F000, "120", rows=rows)
    with pytest.raises(WcofsZetaContractError) as caught:
        zeta_frames(client, BASE, [F000], CYCLE, ORIGIN, 60, 2, 3, 3, 5, LAT, LON)
    assert caught.type is WcofsZetaContractError
    assert client.calls == [*client.metadata, BASE + F000 + ASCII_QUERY]


def test_c2_malformed_ascii_keeps_dap_error():
    """C2: Catch treating a malformed payload as a skipped forecast step."""
    client = Client()
    client.add_frame(F000, "120", rows="[0][0], invalid, 0.5, 0.75")
    with pytest.raises(ValueError) as caught:
        zeta_frames(client, BASE, [F000], CYCLE, ORIGIN, 60, 2, 3, 3, 5, LAT, LON)
    assert caught.type is ValueError
    assert client.calls == [*client.metadata, BASE + F000 + ASCII_QUERY]


def test_c3_frames_feed_ssh_layer_unchanged():
    """C3: Catch losing fill/row alignment; also pin C1 metadata source and C2 read order and time bounds."""
    client = Client(DECOYS[0])
    client.add_frame(F000, "119")  # exactly 60 s early
    client.add_frame(F003, "301", rows="[0][0], 1, 0.5, 0.5\n[0][1], 0, -9999, 0.5")  # 60 s late
    client.add_frame(F072, "4440", rows="[0][0], -0.5, -0.5, -0.5\n[0][1], -9999, -0.5, -0.5")
    files = [DECOYS[0], F072, *DECOYS[1:], F003, F000]

    result = zeta_frames(client, BASE, files, CYCLE, ORIGIN, 60, 2, 3, 3, 5, LAT, LON)
    assert result == [
        {"time": 1767225540, "latitudes": LAT, "longitudes": LON, "units": "meters",
         "fill_value": -9999.0, "source_file": F000, "zeta": [[0.25, -9999, 0.75], [0.5, 0.5, 0.5]]},
        {"time": 1767236460, "latitudes": LAT, "longitudes": LON, "units": "meters",
         "fill_value": -9999.0, "source_file": F003, "zeta": [[1, 0.5, 0.5], [0, -9999, 0.5]]},
        {"time": 1767484800, "latitudes": LAT, "longitudes": LON, "units": "meters",
         "fill_value": -9999.0, "source_file": F072, "zeta": [[-0.5, -0.5, -0.5], [-9999, -0.5, -0.5]]},
    ]
    assert client.calls == [*client.metadata, *(BASE + file + ASCII_QUERY for file in (F000, F003, F072))]

    layer = ssh_layer(result, CYCLE, [0.04, 0.04])
    assert layer["frames"] == [
        {"time": 1767225540, "source_file": F000, "valid_cells": 5, "total_cells": 6,
         "cells": [[35.0, -121.0, -25.0], [35.0, -120.92, 25.0],
                   [35.04, -121.0, 0.0], [35.04, -120.96, 0.0], [35.04, -120.92, 0.0]]},
        {"time": 1767236460, "source_file": F003, "valid_cells": 5, "total_cells": 6,
         "cells": [[35.0, -121.0, 50.0], [35.0, -120.96, 0.0], [35.0, -120.92, 0.0],
                   [35.04, -121.0, -50.0], [35.04, -120.92, 0.0]]},
        {"time": 1767484800, "source_file": F072, "valid_cells": 5, "total_cells": 6,
         "cells": [[35.0, -121.0, 0.0], [35.0, -120.96, 0.0], [35.0, -120.92, 0.0],
                   [35.04, -120.96, 0.0], [35.04, -120.92, 0.0]]},
    ]


def test_c3_sorts_by_valid_time_and_preserves_optional_metadata():
    """C3: Catch returning read order at equal forecast hours, hardcoding metadata, or rounding epoch seconds."""
    client = Client(das='Attributes { zeta { String units "m"; } }')
    client.add_frame(F000, "7200.75", rows="[0][0], 1, 2, 3\n[0][1], 4, 5, 6")
    second = "alternate/" + F000
    client.add_frame(second, "7199.75", rows="[0][0], 6, 5, 4\n[0][1], 3, 2, 1")
    result = zeta_frames(client, BASE, [F000, second], CYCLE, ORIGIN, 1, 2, 3, 3, 5, LAT, LON)
    assert result == [
        {"time": 1767225599, "latitudes": LAT, "longitudes": LON, "zeta": [[6, 5, 4], [3, 2, 1]],
         "units": "m", "fill_value": None, "source_file": second},
        {"time": 1767225600, "latitudes": LAT, "longitudes": LON, "zeta": [[1, 2, 3], [4, 5, 6]],
         "units": "m", "fill_value": None, "source_file": F000},
    ]
