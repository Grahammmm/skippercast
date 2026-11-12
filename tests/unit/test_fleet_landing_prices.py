"""Landing-pages offering merge (RF1315-9): two different known prices keep the price unknown for good.

Offline and serverless: helper cases use real fact-bearing Offerings; boat cases run the real
``_Page.boat`` over synthetic rate tables served from an in-memory map. Every name and URL is invented.
"""
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
import json
import unittest

from skippercast.fleet.adapters.base import Fact, Offering, RunContext
from skippercast.fleet.adapters.landing_pages import _merge_offering, _Page
from skippercast.fleet.config import Binding, Landing

T0 = "2026-10-05T09:47:00Z"
HOST = "www.example-harbor.example.com"
FLEET, BOAT = f"https://{HOST}/fleet.php", f"https://{HOST}/boats/fixture.php"
LANDING = Landing("example-harbor-landing", "Example Harbor Landing", "example-port", (33.0, -117.0), None)
BINDING = Binding("example-harbor-landing", "landing-pages", True,
                  {"landing": "example-harbor-landing", "template": "fr-fleet-php", "url": FLEET}, "facts-only")


def offering(price, name="Overnight", season=(None, None), row=0):
    value = {"name": name, "trip_type": "overnight", "row": row}
    if price is not None:
        value["price_cents"] = price
    fact = Fact("trip_types[]", value, "landing-pages", BOAT, "page", 0.9, "facts-only", T0)
    return Offering(name, "overnight", (fact,), price_cents=price, price_basis="private",
                    season_from=season[0], season_to=season[1])


def merged(*prices):
    """Merge one offering per price (each its own row fact); the aggregate price after every merge."""
    offerings, out = {}, []
    for i, price in enumerate(prices):
        key = _merge_offering(offerings, offering(price, row=i))
        out.append(offerings[key].price_cents)
    return out, offerings[key]


def page(rows, schedule=""):
    trs = "".join(f"<tr><td>{name}</td><td>All Year</td><td>30</td><td>{price}</td></tr>" for name, price in rows)
    html = (f'<html><body><div class="pod_boat_details"><h2>Fixture Boat</h2></div><div id="rates-container">'
            f"<table><tr><td>Trip Types</td><td>Season</td><td>Anglers</td><td>Price</td></tr>{trs}</table></div>"
            f"{schedule}</body></html>")
    requests = []

    def get(url):
        requests.append(url)
        return SimpleNamespace(body=html.encode(), final_url=url)

    net = SimpleNamespace(get=get, skips=[])
    ctx = RunContext(SimpleNamespace(landings=(LANDING,)), net, Path("."), lambda: T0)
    card = {"name": "Fixture Boat", "link": BOAT, "captains": [], "photo": None}
    landing = _Page(BINDING, ctx, LANDING)
    landing.times[FLEET] = T0  # discover fetched the fleet page first
    return landing.boat(card, FLEET), requests


class MergeHelperTests(unittest.TestCase):
    def test_third_row_cannot_resolve_conflict(self):
        for third in (10000, 20000, 30000):
            prices, kept = merged(10000, 20000, third, third)
            self.assertEqual(prices, [10000, None, None, None])
            values = sorted({f.value["price_cents"] for f in kept.facts})
            self.assertEqual(values, sorted({10000, 20000, third}))
            self.assertEqual(len(kept.facts), 4)  # every row's fact is kept, in order
            self.assertEqual([f.value["row"] for f in kept.facts], [0, 1, 2, 3])

    def test_permutations_agree_on_price_not_metadata(self):
        for order in set(permutations((10000, 10000, 20000))):
            self.assertIsNone(merged(*order)[0][-1], order)

    def test_unknown_is_not_conflict(self):
        cases = {(None, 10000): 10000, (10000, None): 10000, (None, None): None, (10000, 10000, 10000): 10000,
                 (0, None): 0, (None, 0): 0, (0, 0): 0, (0, 10000): None}
        for prices, want in cases.items():
            self.assertEqual(merged(*prices)[0][-1], want, prices)
        self.assertEqual(merged(10000, 20000, None, 10000)[0], [10000, None, None, None])

    def test_keys_are_isolated(self):
        offerings = {}
        for price in (10000, 20000, 10000):
            _merge_offering(offerings, offering(price))
        for price in (10000, 10000):
            _merge_offering(offerings, offering(price, name="Day Trip"))
            _merge_offering(offerings, offering(price, season=("05-01", "10-31")))
        self.assertEqual([o.price_cents for o in offerings.values()], [None, 10000, 10000])

    def test_inputs_are_not_mutated(self):
        a, b, c = offering(10000, row=0), offering(20000, row=1), offering(10000, row=2)
        before = [x.facts[0].value.copy() for x in (a, b, c)]
        offerings = {}
        for x in (a, b, c):
            _merge_offering(offerings, x)
        self.assertEqual([x.facts[0].value for x in (a, b, c)], before)
        self.assertEqual((a.price_cents, b.price_cents, c.price_cents), (10000, 20000, 10000))


class BoatPageTests(unittest.TestCase):
    def test_real_rate_table_preserves_contradiction(self):
        for order in set(permutations(("$100", "$200", "$100"))):
            boat, requests = page([("Overnight", p) for p in order])
            self.assertEqual(requests, [BOAT])
            self.assertEqual(len(boat.offerings), 1)
            o = boat.offerings[0]
            self.assertIsNone(o.price_cents, order)
            self.assertEqual(sorted(f.value["price_cents"] for f in o.facts), [10000, 20000])  # deduplicated
            row = json.loads(json.dumps(boat.as_dict()))["offerings"][0]
            self.assertIsNone(row["price_cents"])
            self.assertEqual(set(row), set(offering(None).as_dict()))  # no extra fields
            self.assertIsNone(o.op("XX-vessel", T0)["price_cents"])
            for f in o.facts:
                self.assertEqual((f.source_url, f.retrieved_at, f.rights), (BOAT, T0, "facts-only"))
                self.assertIn(f, boat.facts)

    def test_duplicate_only_and_fresh_boat_stay_known(self):
        page([("Overnight", "$100"), ("Overnight", "$200")])  # another boat conflicted first
        boat, _ = page([("Overnight", "$100"), ("Overnight", "$100"), ("Overnight", "$100")])
        self.assertEqual([o.price_cents for o in boat.offerings], [10000])
        self.assertEqual(len(boat.offerings[0].facts), 1)

    def test_unrelated_fields_and_departures_unchanged(self):
        schedule = ('<table><tr><td class="trip-name" data-trip-id="1"><strong>Fixture Boat</strong><br>Overnight</td>'
                    '<td data-trip-id="1"><div class="trip-depart">Mon. 11-2-2026 <br>10:00 PM</div>'
                    '<div class="trip-load">24</div><div class="trip-price"><b>$150</b></div></td></tr></table>')
        boat, _ = page([("Overnight", "$100"), ("Overnight", "$200"), ("Overnight", "$100"), ("Day Trip", "$80")],
                       schedule)
        by_name = {o.name: o for o in boat.offerings}
        self.assertEqual(list(by_name), ["Private charter: Overnight", "Private charter: Day Trip", "Overnight"])
        self.assertEqual([(o.price_cents, o.capacity, o.season_from) for o in by_name.values()],
                         [(None, 30, None), (8000, 30, None), (15000, 24, None)])
        self.assertEqual([(d.offering.name, d.date, d.departs_local, d.price_cents) for d in boat.departures],
                         [("Overnight", "2026-11-02", "22:00", 15000)])
        self.assertNotIn("conflict", json.dumps(boat.as_dict()))


if __name__ == "__main__":
    unittest.main()
