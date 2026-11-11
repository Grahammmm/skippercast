"""Landing-page source clocks: impossible AM/PM fields are unknown, never wrapped or fatal (RF0645-8). No server."""
from pathlib import Path
from types import SimpleNamespace
import unittest

from skippercast.fleet.adapters import get
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.landing_pages import _schedule, local_time, parse_html
from skippercast.fleet.config import Binding, Landing

HOST = "www.example-harbor.example.com"
T0 = "2026-10-05T09:47:00Z"


def row(trip_id, boat, depart, back, price="$80.00", load="40"):
    return (f'<tr><td class="trip-cell" data-trip-id="{trip_id}"><div class="row">'
            f'<div class="trip-info"><strong>{boat}</strong><br>AM Half Day</div>'
            f'<div class="trip-depart">Tue. 10-6-26 <br>{depart}</div>'
            f'<div class="trip-return">Tue. 10-6-26 <br>{back}</div>'
            f'<div class="trip-load">{load}</div><div class="trip-price">{price}</div></div></td></tr>')


def schedule(*rows, boat="Kelp Fixture"):
    return _schedule(parse_html("<table><tbody>" + "".join(rows) + "</tbody></table>"), boat)["AM Half Day"]


class LocalTimeTests(unittest.TestCase):
    def test_valid_twelve_hour_boundaries(self):
        for text, want in (("12:00 AM", "00:00"), ("12:00 PM", "12:00"), ("1:00 AM", "01:00"), ("1:00 PM", "13:00"),
                           ("11:59 PM", "23:59"), ("Tue. 10-6-26 6:30 a.m.", "06:30"), ("10-6-26 6:30pm", "18:30")):
            self.assertEqual(local_time(text), want, text)

    def test_invalid_numeric_fields_are_unknown(self):
        for text in ("00:30 AM", "13:30 PM", "99:00 AM", "06:60 AM", "06:99 AM", "Tue. 10-6-26 06:99 AM"):
            self.assertIsNone(local_time(text), text)
        self.assertIsNone(local_time(None))
        self.assertIsNone(local_time(""))
        self.assertIsNone(local_time("no clock here"))

    def test_oversized_token_does_not_suffix_match(self):
        for text in ("113:30 PM", "6:300 AM", "Tue. 10-6-26 113:30 PM"):
            self.assertIsNone(local_time(text), text)
        self.assertEqual(local_time("10-6-26 6:30 AM"), "06:30")


class ScheduleTests(unittest.TestCase):
    def test_invalid_departure_keeps_dated_row(self):
        rows = schedule(row(1, "Kelp Fixture", "06:99 AM", "12:00 PM"), row(2, "Kelp Fixture", "6:30 AM", "12:00 PM"))
        self.assertEqual(rows[0], {"date": "2026-10-06", "departs": None, "duration_h": None,
                                   "price_cents": 8000, "load": "40"})
        self.assertEqual((rows[1]["departs"], rows[1]["duration_h"]), ("06:30", 5.5))

    def test_invalid_return_withholds_duration_only(self):
        (only,) = schedule(row(1, "Kelp Fixture", "6:30 AM", "12:99 PM"))
        self.assertEqual(only, {"date": "2026-10-06", "departs": "06:30", "duration_h": None,
                                "price_cents": 8000, "load": "40"})
        (both,) = schedule(row(1, "Kelp Fixture", "13:30 PM", "12:99 PM"))
        self.assertEqual((both["departs"], both["duration_h"]), (None, None))
        (same_day,) = schedule(row(1, "Kelp Fixture", "6:30 AM", "12:00 PM"))
        self.assertEqual(same_day["duration_h"], 5.5)


class DiscoverTests(unittest.TestCase):
    def test_discover_continues_and_preserves_provenance(self):
        fleet = ('<html><body><ul class="dropdown-menu">'
                 '<li><a href="/boats/bad.php"><span>Bad Clock</span></a></li>'
                 '<li><a href="/boats/good.php"><span>Good Clock</span></a></li></ul></body></html>')

        def boat(name, depart):
            return (f'<html><body><div class="pod_boat_details"><h2>{name}</h2></div><table><tbody>'
                    + row(1, name, depart, "12:00 PM") + "</tbody></table></body></html>")
        pages = {f"https://{HOST}/fleet.php": fleet, f"https://{HOST}/boats/bad.php": boat("Bad Clock", "06:99 AM"),
                 f"https://{HOST}/boats/good.php": boat("Good Clock", "6:30 AM")}
        requested = []

        class Net:
            skips = []

            def get(self, url, **options):
                requested.append(url)
                return SimpleNamespace(final_url=url, body=pages[url].encode())

        landing = Landing("example-harbor-landing", "Example Harbor Landing", "example-port", (33.0, -117.0), None)
        ctx = RunContext(SimpleNamespace(landings=(landing,)), Net(), Path("."), lambda: T0)
        binding = Binding("example-harbor-landing", "landing-pages", True,
                          {"landing": "example-harbor-landing", "template": "fr-fleet-php",
                           "url": f"https://{HOST}/fleet.php"}, "facts-only")
        boats = {c.name: c for c in get("landing-pages")().discover(binding, ctx)}
        self.assertEqual(list(boats), ["Bad Clock", "Good Clock"])
        self.assertEqual(requested, list(pages))
        for candidate in boats.values():
            for fact in candidate.facts:
                self.assertEqual((fact.rights, fact.retrieved_at), ("facts-only", T0))
        (bad,) = boats["Bad Clock"].departures
        (good,) = boats["Good Clock"].departures
        self.assertIsNone(bad.departs_local)
        self.assertEqual(good.departs_local, "06:30")
        self.assertNotIn("06:99", repr(boats["Bad Clock"]))
