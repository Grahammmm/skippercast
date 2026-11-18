"""F07-09 / SCA-268: charter day columns with the same price keep their exact union of days.

Contract protected: a rate row's day-restricted price columns merge only into the union of their days;
only a price covering all seven days is unrestricted. The bug this fails on: any set of equal-priced day
columns collapsed to a blank label and ``days=None`` ("every day"), so a Friday-only or Mon+Fri rate
looked bookable all week. Offline: synthetic rate tables parsed by the real ``_rates``; invented names.
"""
import pytest

from skippercast.fleet.adapters.landing_pages import _rates, parse_html


def rates(header, *cells):
    head = "".join(f"<td>{h}</td>" for h in ("Trip Types", "Season", "Anglers", *header))
    row = "".join(f"<td>{c}</td>" for c in ("Half Day", "All Year", "30", *cells))
    html = f'<html><body><div id="rates-container"><table><tr>{head}</tr><tr>{row}</tr></table></div></body></html>'
    return [(r["name"], r["price_cents"], r["days"]) for r in _rates(parse_html(html))]


ALL = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def test_friday_only_column_keeps_its_day():  # negative control: used to be blank name and days None
    assert rates(["Friday"], "$2,400") == [("Private charter: Half Day (Friday)", 240000, ("fri",))]


def test_equal_price_monday_and_friday_stay_two_days():  # negative control for the cited collapse
    assert rates(["Mon", "Fri"], "$2,400", "$2,400") == [
        ("Private charter: Half Day (Mon + Fri)", 240000, ("mon", "fri"))]


def test_equal_price_ranges_not_covering_the_week_keep_the_union():
    assert rates(["Mon - Thu", "Sat - Sun"], "$2,400", "$2,400")[0][2] == ("mon", "tue", "wed", "thu", "sat", "sun")


def test_different_prices_stay_separate():
    assert rates(["Mon - Thu", "Fri - Sun"], "$2,400", "$2,650") == [
        ("Private charter: Half Day (Mon - Thu)", 240000, ("mon", "tue", "wed", "thu")),
        ("Private charter: Half Day (Fri - Sun)", 265000, ("fri", "sat", "sun"))]


def test_equal_price_covering_the_whole_week_is_unrestricted():  # positive control: all seven days = no restriction
    assert rates(["Mon - Thu", "Fri - Sun"], "$2,400", "$2,400") == [("Private charter: Half Day", 240000, None)]


def test_equal_prices_merge_across_other_price_groups():
    out = rates(["Mon", "Fri", "Sat"], "$2,400", "$2,650", "$2,400")
    assert out == [("Private charter: Half Day (Mon + Sat)", 240000, ("mon", "sat")),
                   ("Private charter: Half Day (Fri)", 265000, ("fri",))]


@pytest.mark.parametrize("header", [["Price"], ["Cash", "Credit"]])
def test_unlabelled_payment_columns_are_unchanged(header):
    assert rates(header, *["$2,400"] * len(header)) == [("Private charter: Half Day", 240000, None)]
