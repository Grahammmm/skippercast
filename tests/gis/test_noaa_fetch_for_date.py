"""Exact UTC-day selection and subset reads, with no NOAA network calls."""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from skippercast import http
from skippercast.pipeline import noaa_chlorophyll as chl
from skippercast.pipeline import noaa_sst as sst
from tests.gis.test_noaa_chlorophyll import BOUNDS as CHL_BOUNDS, FIXTURES
from tests.gis import test_noaa_sst as sst_fixtures
from tests.gis.test_noaa_sst_fetch import FakeClient, catalog, name


def chl_path(code):
    return f"{chl.DIRECTORY}/V{code}_D1_NPP-N20_WW00_chloci.nc"


def xml_catalog(*paths):
    entries = "".join(f'<dataset urlPath="{path}"/>' for path in paths)
    return f"<catalog>{entries}</catalog>".encode()


@pytest.mark.parametrize("day,stamp,invalid", [
    (date(2025, 12, 31), "20251231012000", "20251231250000"),
    (date(2024, 2, 29), "20240229012000", "20240230012000"),
])
def test_sst_uses_requested_year_and_valid_timestamp(day, stamp, invalid):
    # A date prefix alone would include an invalid clock; a basename alone would include the wrong folder.
    url = f"{sst.CATALOG}/{day.year}/catalog.xml"
    path = f"{sst.PATH}/{day.year}/{name(stamp)}"
    client = FakeClient(xml_catalog(f"{sst.PATH}/{day.year}/{name(invalid)}",
                                    f"{sst.PATH}/{day.year + 1}/{name(stamp)}", path))
    assert sst.dated_file(client, day) == (path, url)
    assert client.urls == [url]


@pytest.mark.parametrize("day,code", [
    (date(2024, 12, 30), "2024365"),
    (date(2024, 12, 31), "2024366"),
    (date(2025, 1, 1), "2025001"),
    (date(2025, 12, 31), "2025365"),
    (date(2026, 1, 1), "2026001"),
])
def test_chlorophyll_matches_exact_ordinal_without_live_window(day, code):
    # Rolling invalid ordinals into the next/previous year or applying the live cap loses archived days.
    path = chl_path(code)
    other_codes = {"2024365", "2024366", "2025001", "2025365", "2026001", "2026002"} - {code}
    client = FakeClient(xml_catalog(*(chl_path(c) for c in sorted(other_codes)),
                                    chl_path("2025366"), chl_path("2026000"),
                                    f"{chl.DIRECTORY}/nested/{path.rsplit('/', 1)[-1]}", path))
    assert chl.dated_file(client, day) == (datetime(day.year, day.month, day.day, tzinfo=timezone.utc), path)
    assert client.urls == [chl.CATALOG]


@pytest.mark.parametrize("adapter,body", [
    (sst, catalog(2025, "20251230000000", "20251231240000")),
    (sst, http.HTTPStatusError("not found", 404)),
    (chl, xml_catalog(chl_path("2025364"), chl_path("2026000"))),
])
def test_absent_day_names_date_instead_of_substituting(adapter, body):
    # Neither a neighboring day nor an impossible timestamp can fill the gap.
    with pytest.raises(ValueError, match="2025-12-31"):
        adapter.dated_file(FakeClient(body), date(2025, 12, 31))


@pytest.mark.parametrize("adapter,body", [
    (sst, catalog(2025, "20251231000000", "20251231010000")),
    (sst, catalog(2025, "20251231000000", "20251231000000")),
    (chl, xml_catalog(chl_path("2025365"), chl_path("2025365"))),
])
def test_multiple_entries_for_day_are_ambiguous(adapter, body):
    # First-wins and deduplication would both conceal ambiguous catalog entries.
    with pytest.raises(ValueError, match="Ambiguous.*2025-12-31"):
        adapter.dated_file(FakeClient(body), date(2025, 12, 31))


@pytest.mark.parametrize("adapter", [sst, chl])
def test_future_utc_day_is_refused_before_catalog_access(adapter):
    # The client's local date is already Jan 3, but UTC is not.
    client = FakeClient()
    client.now = datetime(2026, 1, 3, 1, tzinfo=timezone(timedelta(hours=2)))
    with pytest.raises(ValueError, match="2026-01-03.*future"):
        adapter.dated_file(client, date(2026, 1, 3))
    assert client.urls == []


@pytest.mark.parametrize("adapter,bounds,day,path,body,subset,variables,sample,valid", [
    (sst, sst_fixtures.BOUNDS, date(2026, 9, 23), f"{sst.PATH}/2026/{name('20260923120000')}",
     catalog(2026, "20260924120000", "20260923120000"), sst_fixtures.NoaaSstTests().fixture,
     ["analysed_sst", "analysis_error", "mask"], "2026-09-23T12:00:00Z", 2),
    (chl, CHL_BOUNDS, date(2026, 10, 28), chl_path("2026301"),
     xml_catalog(chl_path("2026302"), chl_path("2026301"), chl_path("2026300")),
     (FIXTURES / "morro-bay-V2026301.nc").read_bytes, ["chl_oci"], "2026-10-28T12:00:00Z", 0),
])
def test_fetch_reads_only_the_dated_subset(adapter, bounds, day, path, body, subset, variables, sample, valid):
    # A latest-file lookup would request another file, and a gap must not trigger walk-back.
    class SubsetClient(FakeClient):
        def get(self, url, as_binary=False):
            assert as_binary == ("/ncss/" in url)  # NetCDF must not be decoded as text.
            return super().get(url, as_binary=as_binary)

    client = SubsetClient(body, subset())
    client.now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    result = adapter.fetch_for_date(client, bounds, day)
    catalog_url = f"{sst.CATALOG}/2026/catalog.xml" if adapter is sst else chl.CATALOG
    assert client.urls == [catalog_url, result["query_url"]]
    assert result["catalog_url"] == catalog_url
    assert result["dataset"] == path
    assert result["requested_bounds"] == bounds
    assert (result["sample_at"], result["valid_cells"]) == (sample, valid)
    request = urlsplit(result["query_url"])
    assert (request.scheme, request.netloc, request.path) == ("https", "coastwatch.noaa.gov", f"/thredds/ncss/grid/{path}")
    assert parse_qs(request.query) == {
        "var": variables, "accept": ["netcdf"],
        "north": [str(bounds["latitude"][1])], "south": [str(bounds["latitude"][0])],
        "west": [str(bounds["longitude"][0])], "east": [str(bounds["longitude"][1])],
    }
