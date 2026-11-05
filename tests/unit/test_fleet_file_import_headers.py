"""RF1410-7: file-import refuses two recognized columns for one canonical fact (synthetic CSVs only).

DictReader silently keeps the last value of a repeated header and the alias map kept the first of two aliases, so a
file could name two vessels or two FG numbers and import one of them. The ambiguity is refused before any row is read.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.file_import import FileImport, FileImportError, read_rows
from skippercast.fleet.config import load_region
from skippercast.fleet.runs import Run

REGION = load_region("CA")
CDFW, SCOUT = "cdfw-cpfv-v1", "scout-candidates-v1"
SCOUT_HEAD = "port_id,{boat},operator,class,landing,website,evidence_urls"


def _refused(data: bytes, column_set: str = CDFW) -> str:
    with pytest.raises(FileImportError) as caught:
        read_rows(data, column_set)
    return str(caught.value)


@pytest.mark.parametrize("data", [
    b"Vessel Name,Vessel Name,FG Number\nFirst Boat,Second Boat,FG1\n",
    b"FG Number,Vessel Name,Vessel Name\nFG1,First Boat,Second Boat\n",
    b"Vessel Name,Vessel Name,FG Number\n",                      # header only
    b"Vessel Name,Vessel Name,FG Number\nSame Boat,Same Boat,FG1\n",  # equal values do not excuse it
])
def test_duplicate_literal_header_refused(data):
    message = _refused(data)
    assert message == "cdfw-cpfv-v1: ambiguous column vessel_name"
    assert "Boat" not in message and "FG1" not in message


@pytest.mark.parametrize("header,canonical", [
    ("Vessel Name,FG Number,FG", "fg_number"),
    ("Vessel Name,FG Number,fg_no", "fg_number"),
    ("Vessel Name,Vessel Name,FG", "vessel_name"),
    ("Vessel Name,VESSEL_NAME,FG", "vessel_name"),
    ("Vessel Name,Vessel-Name,FG", "vessel_name"),
    ("Vessel Name,Boat Name,FG", "vessel_name"),
    ("Vessel Name,FG,CPFV Licence Number,CPFV License #", "licence_number"),
])
def test_canonical_alias_collision_refused(header, canonical):
    row = ",".join("x" for _ in header.split(","))
    assert _refused(f"{header}\n{row}\n".encode()) == f"cdfw-cpfv-v1: ambiguous column {canonical}"


@pytest.mark.parametrize("boat", ["boat,Boat", "boat,BOAT", "Boat,boat"])
def test_scout_boat_case_variants_refused(boat):
    head = SCOUT_HEAD.format(boat=boat)
    assert _refused(f"{head}\nSD,A,B,c,d,e,f,g\n".encode(), SCOUT).startswith("scout-candidates-v1: ambiguous column vessel_name")


def test_discover_emits_no_partial_candidates(tmp_path: Path):
    run = Run("CA", "20261005T100000Z-abcdef", var=tmp_path)
    ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: "2026-10-05T10:00:00Z")
    inputs = tmp_path / "CA" / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "cpfv.csv").write_bytes(b"Vessel Name,FG Number,Vessel Name\nFirst Boat,FG1,Second Boat\nThird Boat,FG2,Fourth Boat\n")
    binding = SimpleNamespace(id="cpra-cpfv", adapter="file-import", enabled=True, rights="public-record",
                              params={"path": "inputs/cpfv.csv", "columns": CDFW})
    adapter = FileImport()
    with pytest.raises(FileImportError, match="ambiguous column vessel_name"):
        list(adapter.discover(binding, ctx))
    assert adapter.report["cpra-cpfv"]["rows"] == 0 and adapter.report["cpra-cpfv"]["candidates"] == 0


def test_unambiguous_and_unknown_columns_unchanged():
    data = b"Notes,FG Number,Extra,Extra,Vessel Name,Licensee\nn1,FG1,e1,e2,Test Boat,Sea LLC\n"
    assert read_rows(data, CDFW) == [{"fg_number": "FG1", "vessel_name": "Test Boat", "licensee_name": "Sea LLC"}]
    scout = f"{SCOUT_HEAD.format(boat='Boat')},extra\nSD,Sea Boat,Op,c,d,e,f,g\n".encode()
    assert read_rows(scout, SCOUT)[0]["vessel_name"] == "Sea Boat"


def test_missing_required_and_malformed_remain_named_refusals():
    assert _refused(b"Vessel Name\nA\n") == "cdfw-cpfv-v1: missing column(s) fg_number or licence_number"
    assert _refused(b"FG Number\nFG1\n") == "cdfw-cpfv-v1: missing column(s) vessel_name"
    assert "CSV unreadable near line" in _refused(b"Vessel Name,FG Number\na\x00b,FG1\n")
