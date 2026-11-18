import pytest

from skippercast.pipeline.parsers import charter_reports


@pytest.mark.parametrize(
    ("qualifier", "disposition"),
    [
        (" Released", "released"),
        (" (Released)", "released"),
        (" ( rElEaSeD )", "released"),
        ("", "reported"),
        (" (unverified)", "reported"),
        (" (not released)", "reported"),
        (" (retained)", "reported"),
    ],
)
def test_charter_catch_disposition(qualifier, disposition):
    page = f'''Fish Counts September 20, 2026
    <tr><td><a href="/boats/fixture"><b>Fixture Boat</b></a>Fixture Landing</td>
    <td>3 Anglers</td><td>2 Rockfish{qualifier}</td></tr>'''
    result = charter_reports(
        page, "2026-09-20", "https://example.invalid/fish-counts",
        ports={"Fixture Landing": "Fixture Port"},
    )
    assert result["reports"][0]["catches"] == [
        {"species": "rockfish", "label": "Rockfish", "count": 2, "disposition": disposition}
    ]
