"""F07-03: an operator page is not evidence that every number is a business line."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.operator_site import OperatorSite

SITE = "https://operator.example/"
BINDING = SimpleNamespace(id="operator-site", params={}, rights="facts-only")


class FixtureNet:
    def __init__(self, pages):
        self.pages = pages

    def allow_host(self, host):
        assert host in {"operator.example", "www.operator.example"}

    def get(self, url, *, max_bytes):
        return SimpleNamespace(final_url=url, headers={}, body=self.pages[url].encode())


def phones(body, **pages):
    region = SimpleNamespace(is_off_limits=lambda _: False)
    net = FixtureNet({SITE: body, **{SITE + path: page for path, page in pages.items()}})
    ctx = RunContext(region, net, Path("."), lambda: "2026-10-05T10:00:00Z")
    return [(f.value, f.confidence, f.flags, f.source_url)
            for f in OperatorSite().enrich({"website": SITE}, BINDING, ctx)
            if f.field == "phone_business"]


@pytest.mark.parametrize("reverse", [False, True])
def test_only_booking_office_is_emitted_on_mixed_page(reverse):
    rows = [
        '<p>Emergency personal mobile (not for bookings): (202) 555-0101</p>',
        '<p>Third-party reservations: <a href="tel:202-555-0102">(202) 555-0102</a></p>',
        '<p><a href="tel:202-555-0103">(202) 555-0103</a></p>',
        '<p><a href="tel:202-555-0104" aria-label="Emergency only">Office</a></p>',
        '<p><strong>Booking office:</strong> (202) 555-0100</p>',
    ]
    assert phones("".join(reversed(rows) if reverse else rows)) == [("+12025550100", 0.7, (), SITE)]


def test_booking_link_with_local_label_is_a_positive_control():
    assert phones('<p><a href="tel:202-555-0100"><span>Call for bookings</span></a></p>') == [
        ("+12025550100", 0.8, (), SITE),
    ]


def test_context_does_not_extend_across_contact_entries():
    body = '<h2>Bookings</h2><p>(202) 555-0101</p><p>Office: (202) 555-0100 (202) 555-0102</p>'
    assert phones(body) == []


@pytest.mark.parametrize("contact", [
    '<p>Personal, not for booking: (202) 555-0101 and (202) 555-0102</p>',
    '<p>Personal, not for booking: <a href="tel:202-555-0101">first</a> and '
    '<a href="tel:202-555-0102">second</a></p>',
])
def test_multi_number_exclusion_vetoes_each_duplicate_before_the_site_cap(contact):
    body = ('<p>Booking line: (202) 555-0101</p><p>Bookings: (202) 555-0102</p>'
            '<p>Office: (202) 555-0100</p><a href="/contact">Contact</a>')
    assert phones(body, contact=contact) == [("+1" + "202" + "555" + "0100", 0.7, (), SITE)]


def test_explicit_exclusion_vetoes_a_duplicate_before_the_site_cap():
    body = ('<p>Booking line: (202) 555-0101</p><p>Bookings: (202) 555-0100</p>'
            '<p>Reservations: (202) 555-0102</p><p>Office: (202) 555-0103</p>'
            '<a href="/contact">Contact</a>')
    assert phones(body, contact='<p>Personal phone, not for booking: (202) 555-0101</p>') == [
        ("+12025550100", 0.7, (), SITE), ("+12025550102", 0.7, (), SITE), ("+12025550103", 0.7, (), SITE),
    ]
