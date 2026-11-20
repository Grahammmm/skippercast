import importlib.util

from tests._support import ROOT


def test_status_distinguishes_ranked_unranked_and_unrecorded_screen_outputs():
    # Guard against treating ready unranked reaches as ranked, or missing legacy counts as zero.
    spec = importlib.util.spec_from_file_location("seafloor_status", ROOT / "research/scripts/seafloor_status.py")
    assert spec is not None and spec.loader is not None
    status = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(status)

    def reach(region, tier2=0, **counts):
        return dict(id=region, region=region, tier1_km2=2, tier2_km2=tier2,
                    selected_valid_km2=2, screen={"status": "ready"}, **counts)

    ledger = {"input_hash": "synthetic", "reaches": [
        reach("ranked", tier2=1, search_area_count=0, classified_area_count=0),
        reach("search", search_area_count=3, classified_area_count=0),
        reach("classified", search_area_count=0, classified_area_count=2),
        reach("empty", search_area_count=0, classified_area_count=0),
        reach("legacy", classified_area_count=0),
        reach("legacy-both"),
        dict(reach("held", tier2=1, search_area_count=3, classified_area_count=2),
             screen={"status": "held"}),
    ]}
    table = [[cell.strip() for cell in line.strip("|").split("|")]
             for line in status.render(ledger).splitlines() if line.startswith("|")]
    headings, _, *rows = table
    columns = ["Screen-ready with ranked habitat", "Screen-ready with unranked search areas",
               "Screen-ready with unranked classified areas", "Live publication"]
    results = {row[0]: tuple(row[headings.index(column)] for column in columns) for row in rows}
    assert results == {name: (*counts, "Not verified by this report") for name, counts in {
        "ranked": ("1", "0", "0"),
        "search": ("0", "1", "0"),
        "classified": ("0", "0", "1"),
        "empty": ("0", "0", "0"),
        "legacy": ("0", "0 (1 unknown)", "0"),
        "legacy-both": ("0", "0 (1 unknown)", "0 (1 unknown)"),
        "held": ("0", "0", "0"),
    }.items()}
