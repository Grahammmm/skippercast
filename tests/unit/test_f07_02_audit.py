"""F07-02: CDFW licence imports keep only unambiguous business licensees."""
import csv
import json
from types import SimpleNamespace
from typing import cast

from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.file_import import FileImport


def test_cdfw_withholds_mixed_licensee_names(tmp_path, capsys, caplog):
    businesses = ("Synthetic Tidal Charters LLC", "Synthetic Skiff Services, Inc.")
    withheld = (
        "Pat Placeholder dba Synthetic Tidal Charters LLC",
        "Dotted Placeholder D.B.A. Synthetic Tidal Charters LLC",
        "Synthetic Tidal Charters c / o Care Placeholder LLC",
        "Synthetic Tidal Charters care-of Alternate Placeholder LLC",
        "Estate of Estate Placeholder LLC",
        "Family Placeholder Estate LLC",
        "Trustee Placeholder as trustee for Synthetic Tidal Charters LLC",
        "SurnamePlaceholder, GivenPlaceholder LLC",
    )
    values = businesses + withheld
    rows = [(f"Synthetic Boat {index}", f"FG{index}", value) for index, value in enumerate(values, 1)]
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    with (inputs / "licences.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("Vessel Name", "FG Number", "Licensee"))
        writer.writerows(rows)
    binding = SimpleNamespace(id="synthetic-cpfv", rights="public-record", params={
        "path": "inputs/licences.csv", "columns": "cdfw-cpfv-v1", "source_url": "https://example.invalid/records",
    })
    ctx = cast(RunContext, SimpleNamespace(region=SimpleNamespace(ports=()), net=None,
                                           run_dir=tmp_path / "runs" / "test", clock=lambda: "2026-10-05T10:00:00Z"))

    adapter = FileImport()
    candidates = list(adapter.discover(binding, ctx))

    assert [candidate.name for candidate in candidates] == [row[0] for row in rows]
    operators = {candidate.name: fact.value for candidate in candidates
                 for fact in candidate.facts if fact.field == "operator_business"}
    assert operators == {row[0]: value for row, value in zip(rows, businesses)}
    assert adapter.report[binding.id]["individual_licensees_dropped"] == len(withheld)
    captured = capsys.readouterr()
    emitted = json.dumps([candidate.as_dict() for candidate in candidates]) + json.dumps(adapter.report)
    emitted += captured.out + captured.err + caplog.text
    for name in ("Pat Placeholder", "Dotted Placeholder", "Care Placeholder", "Alternate Placeholder", "Estate Placeholder",
                 "Family Placeholder", "Trustee Placeholder", "SurnamePlaceholder", "GivenPlaceholder"):
        assert name not in emitted
