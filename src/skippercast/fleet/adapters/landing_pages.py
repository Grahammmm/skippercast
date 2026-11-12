"""The ``landing-pages`` adapter (design section 6): a landing's fleet pages.

Two templates, chosen per binding (``params.template``):

- ``fr-fleet-php``: the FishingReservations-style pages many California landings
  run. The fleet list (``fleet.php``: one card per boat with name, link, photo
  and captains) and each boat page on the same host (captains, boat website,
  length x beam, capacity, the "Charter Rates" table and the "Upcoming Trips"
  schedule rows). Rate rows become ``private`` offerings, one per day column
  with its own price; schedule rows become ``per-person`` offerings by trip name
  and dated departures.
- ``generic``: names and links only, from links that look like boat pages.

Facts only (the binding's ``rights``): never owners, mailing addresses, trip
comments, open spots or any free text. Photos are recorded as an https link plus
an attribution (``photos[]`` = ``{url, attribution}``); image bytes are never
fetched. Every fetch goes through ``ctx.net`` (``FleetSession``), which records a
refused URL in ``ctx.net.skips``; a failed fetch is recorded there as
``fetch-error``. A page whose structure no longer matches its template (a fleet
page listing no boats, a boat page without the boat-details, rates or schedule
blocks) raises ``LayoutError`` and is recorded as a ``layout`` skip, never as an
empty result.

Each candidate's ``record_id`` is the boat's record URL: the boat page link in
``fr-fleet-php`` mode, the list entry's link in ``generic`` mode. Links are
de-duplicated first, so two boats never share one.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
from html.parser import HTMLParser
import re
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import urljoin, urlsplit

from ... import http
from ._html import LayoutError
from .base import Candidate, Departure, Fact, Offering, RunContext, offering_name_norm

ID = "landing-pages"
TEMPLATES = ("fr-fleet-php", "generic")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "template"}
DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_END = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
BOAT_PATH = re.compile(r"/(?:boats?|fleet|our-fleet|charter[-_]boats|charter-fleet|vessels?)/[^/?#]+", re.I)
PRICE = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")
SIZE = re.compile(r"\b(\d{2,3}(?:\.\d)?)\s*(?:ft\.?|feet|')\s*(?:long\s*)?(?:x|by|and)\s*(\d{1,2}(?:\.\d)?)\s*(?:ft\.?|feet|')",
                  re.I)
CAPACITY = re.compile(r"\bBoat Capacity:?\s*(\d{1,4})\b", re.I)
DATE = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2}|\d{4})\b")
TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\b")
ALL_YEAR = re.compile(r"^(?:all\s*(?:year|seasons?)|year[\s-]*round|\d{4}\b.*)$", re.I)
NOT_A_NAME = re.compile(r"^(?:book|more|read|view|details|info|click|schedule|home|rates?|fleet|our fleet)\b", re.I)
CASH = re.compile(r"\bcash\b", re.I)
CREDIT = re.compile(r"\b(?:credit|card)\b", re.I)
PAYMENT = re.compile(r"\b(?:cash|credit|card)\b", re.I)
CAPTAIN_WORD = re.compile(r"\bcapt(?:ain)?s?\b\.?", re.I)
NAME_SPLIT = re.compile(r"\s*(?:&|/|,|;|:|\+|\band\b|\s[-\u2013\u2014]\s)\s*", re.I)
PARTICLES = {"de", "del", "della", "der", "di", "da", "du", "la", "le", "van", "von", "st."}
NOT_A_PERSON = {"tba", "tbd", "various", "rotating", "relief", "owner", "operator", "operators", "crew", "staff",
                "call", "office", "none", "na", "see", "schedule", "the", "boat", "vessel", "licensed", "license",
                "uscg", "master", "deckhand", "deckhands", "mate", "chef", "cook", "and", "or", "with", "our"}
BLOCK = ("br", "p", "div", "tr", "li", "h1", "h2", "h3")


# ---- a small DOM on the standard library parser --------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: Mapping[str, str], parent: "Node | None" = None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter(self) -> Iterator["Node"]:
        """Descendant elements in document order; iterative, so a deeply nested page cannot hit the recursion limit."""
        stack = [iter(self.children)]
        while stack:
            for child in stack[-1]:
                if isinstance(child, Node):
                    yield child
                    stack.append(iter(child.children))
                    break
            else:
                stack.pop()

    def find_all(self, tag: str | None = None, cls: str | None = None) -> list["Node"]:
        return [n for n in self.iter() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes)]

    def find(self, tag: str | None = None, cls: str | None = None) -> "Node | None":
        return next(iter(self.find_all(tag, cls)), None)

    def lines(self, skip: frozenset = frozenset()) -> list[str]:
        """Text split at <br> and block ends, whitespace collapsed; subtrees with a class in ``skip`` left out."""
        parts: list[str] = []
        stack = [iter(self.children)]  # iterative for the same reason as iter()
        while stack:
            for child in stack[-1]:
                if isinstance(child, str):
                    parts.append(child)
                elif not child.classes & skip:
                    if child.tag in BLOCK:
                        parts.append("\n")
                    stack.append(iter(child.children))
                    break
            else:
                stack.pop()
        return [x for x in (" ".join(line.split()) for line in "".join(parts).split("\n")) if x]

    def text(self, skip: frozenset = frozenset()) -> str:
        return " ".join(self.lines(skip))


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.top = Node("#root", {})
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if self.skipping or tag in SKIP:
            self.skipping += tag in SKIP and tag not in VOID
            return
        if tag in ("a", "tr", "td", "th", "li", "p", "option"):  # an unclosed sibling closes implicitly
            node, stop = self.top, {"table": ("tr", "td", "th"), "ul": ("li",), "ol": ("li",), "select": ("option",)}
            while node.parent and node.tag not in stop and not (node.tag == tag):
                node = node.parent
            if node.tag == tag and node.parent:
                self.top = node.parent
        node = Node(tag, {k: v or "" for k, v in attrs}, self.top)
        self.top.children.append(node)
        if tag not in VOID:
            self.top = node

    def handle_endtag(self, tag):
        if self.skipping:
            self.skipping -= tag in SKIP
            return
        node = self.top
        while node.parent and node.tag != tag:
            node = node.parent
        if node.tag == tag and node.parent:
            self.top = node.parent

    def handle_data(self, data):
        if not self.skipping:
            self.top.children.append(data)


def parse_html(text: str) -> Node:
    builder = _Builder()
    builder.feed(text)
    builder.close()
    return builder.root


# ---- value parsers ---------------------------------------------------------------------------

def price_cents(text: str) -> int | None:
    """The first dollar amount in ``text`` in cents ("$10,867.50" -> 1086750); None without one."""
    match = PRICE.search(text or "")
    if not match:
        return None
    cents = (match.group(2) or "0").ljust(2, "0")
    return int(match.group(1).replace(",", "")) * 100 + int(cents)


def cash_cents(text: str) -> int | None:
    """The cash (or only unlabelled) price in a cell, chosen by its label, never by its position.

    "$2,400 Cash $2,484 Credit" and "Cash: $2,400 Credit: $2,484" give 240000; "$983.25 $1,017.66 Credit"
    gives 98325. A cell holding only a credit price, or two different unlabelled prices, gives None.
    """
    text = text or ""
    found = list(PRICE.finditer(text))
    if not found:
        return None
    before = bool(PAYMENT.search(text[:found[0].start()]))  # "Cash: $X" labels precede; "$X Cash" labels follow
    amounts = []
    for i, match in enumerate(found):
        if before:
            label = text[found[i - 1].end() if i else 0:match.start()]
        else:
            label = text[match.end():found[i + 1].start() if i + 1 < len(found) else len(text)]
        kind = "credit" if CREDIT.search(label) else "cash" if CASH.search(label) else ""
        amounts.append((kind, price_cents(match.group(0))))
    pick = {c for k, c in amounts if k == "cash"} or {c for k, c in amounts if k == ""}
    return pick.pop() if len(pick) == 1 else None


def trip_type(name: str) -> str:
    n = name.lower()
    days = re.search(r"\b(\d+(?:[.,]\d)?)\s*-?\s*days?\b", n)
    if "3/4" in n or "three quarter" in n:
        return "three-quarter-day"
    if re.search(r"\b1/2\b|\bhalf\b|twilight", n):
        return "half-day"
    if "overnight" in n:
        return "overnight"
    if days:
        return "multi-day" if float(days.group(1).replace(",", ".")) > 1 else "full-day"
    if "full day" in n or "full-day" in n:
        return "full-day"
    if "charter" in n:
        return "private-charter"
    return "other"


def season_range(text: str) -> tuple[str, str] | None:
    """"May - Oct" -> ("05-01", "10-31"); None when the cell is not a month range."""
    found = re.findall(r"\b(" + "|".join(MONTHS) + r")[a-z]*\b", text.lower())
    if len(found) != 2:
        return None
    start, end = MONTHS.index(found[0]) + 1, MONTHS.index(found[1]) + 1
    return f"{start:02d}-01", f"{end:02d}-{MONTH_END[end - 1]:02d}"


def day_set(label: str) -> tuple[str, ...] | None:
    """"Mon - Thu" -> (mon, tue, wed, thu); "Friday" -> (fri,); None when the header names no day."""
    found = [DAY_KEYS.index(m) for m in re.findall(r"\b(mon|tue|wed|thu|fri|sat|sun)", label.lower())]
    if not found:
        return None
    if len(found) == 2 and "-" in label:
        start, end = found
        return tuple(DAY_KEYS[(start + i) % 7] for i in range((end - start) % 7 + 1))
    return tuple(DAY_KEYS[i] for i in sorted(set(found)))


def local_time(text: str) -> str | None:
    match = TIME.search(text or "")
    if not match:
        return None
    hour = int(match.group(1)) % 12 + (12 if match.group(3).lower() == "p" else 0)
    return f"{hour:02d}:{match.group(2)}"


def local_date(text: str) -> str | None:
    match = DATE.search(text or "")
    if not match:
        return None
    year = int(match.group(3)) + (2000 if len(match.group(3)) == 2 else 0)
    try:
        return datetime(year, int(match.group(1)), int(match.group(2))).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _modal(values: Iterable[Any]) -> Any:
    counts = Counter(v for v in values if v is not None)
    return min(counts, key=lambda v: (-counts[v], v)) if counts else None


def _is_person(name: str) -> bool:
    words = name.split()
    if not 1 <= len(words) <= 4 or len(name) > 60:
        return False
    for word in words:
        if word.lower().strip(".") in NOT_A_PERSON:
            return False
        if word.lower() not in PARTICLES and not (word[0].isupper()
                                                  and all(ch.isalpha() or ch in "'\u2019.-" for ch in word)):
            return False
    return True


def _names(text: str) -> list[str]:
    """Captain names from a captains line: parentheticals, "Captain"/"Capt." and non-name tokens dropped."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text or "")
    parts = (" ".join(p.split()).strip(" .-") for p in NAME_SPLIT.split(CAPTAIN_WORD.sub(" ", text)))
    return list(dict.fromkeys(p for p in parts if p and _is_person(p)))


# ---- the adapter ---------------------------------------------------------------------------

class LandingPages:
    id = ID
    kind = "discover"

    def discover(self, binding, ctx: RunContext) -> Iterable[Candidate]:
        params = binding.params
        if params.get("template") not in TEMPLATES:
            raise ValueError(f"{binding.id}: template must be one of {', '.join(TEMPLATES)}")
        landing = next((x for x in getattr(ctx.region, "landings", ()) if x.id == params.get("landing")), None)
        page = _Page(binding, ctx, landing)
        fleet = page.fetch(params["url"])
        if fleet is None:
            return
        url, root = fleet
        try:
            cards = fleet_entries(root, url, params["template"])
        except LayoutError as error:
            page.record(error.url, "layout", error.detail)
            return
        for card in cards:
            if params["template"] == "generic":
                yield page.candidate(card["name"], card["link"], [page.fact("name", card["name"], url, 0.8)])
            else:
                yield page.boat(card, url)

    def enrich(self, vessel: Mapping[str, Any], binding, ctx: RunContext) -> Iterable[Fact]:
        return ()


def fleet_entries(root: Node, url: str, template: str) -> list[dict]:
    """The boats a fleet page lists ({name, link, ...}); ``LayoutError`` when a page that loaded lists none."""
    if template == "generic":
        cards = [{"name": n, "link": link} for n, link in _boat_links(root, url)]
    else:
        cards = _fleet_cards(root, url) or [{"name": n, "link": link} for n, link in _boat_links(root, url)]
    if not cards:
        raise LayoutError(url, f"no boats on the {template} fleet page")
    return cards


class _Page:
    """One binding's run: fetching, provenance and the parsed candidates."""

    def __init__(self, binding, ctx: RunContext, landing):
        self.binding, self.ctx = binding, ctx
        self.landing_id = binding.params.get("landing")
        self.landing_name = landing.name if landing else None
        self.port = landing.port if landing else None
        self.times: dict[str, str] = {}  # page URL -> when it was fetched

    def record(self, url: str, reason: str, detail: str = "") -> None:
        self.ctx.net.skips.append({"url": url, "reason": reason, "detail": detail[:300]})

    def fetch(self, url: str) -> tuple[str, Node] | None:
        from ..net import Skipped  # net imports config, which imports the adapter registry
        try:
            response = self.ctx.net.get(url)
        except Skipped:
            return None  # FleetSession has recorded why in ctx.net.skips
        except http.SourceError as error:
            self.record(url, "fetch-error", type(error).__name__)
            return None
        final = response.final_url or url
        self.times[url] = self.times[final] = self.ctx.clock()
        return final, parse_html(response.body.decode("utf-8", "replace") if response.body else "")

    def fact(self, field: str, value: Any, url: str, confidence: float = 0.9) -> Fact:
        return Fact(field, value, ID, url, "page", confidence, self.binding.rights, self.times[url])

    def candidate(self, name: str, record_id: str, facts: list[Fact], **extra: Any) -> Candidate:
        source = facts[0].source_url
        if self.landing_name:
            facts.append(self.fact("landing", self.landing_name, source))
        if self.port:
            facts.append(self.fact("port", self.port, source))
        return Candidate(ID, name, self.port, self.landing_id, facts=tuple(facts), record_id=record_id, **extra)

    def photo(self, src: str | None, base: str) -> dict | None:
        if not src:
            return None
        url = urljoin(base, src.strip())
        credit = self.landing_name or urlsplit(base).hostname or ""
        return {"url": url, "attribution": credit} if urlsplit(url).scheme == "https" and credit else None

    def boat(self, card: dict, fleet_url: str) -> Candidate:
        facts = [self.fact("name", card["name"], fleet_url, 0.9)]
        for captain in card.get("captains", ()):
            facts.append(self.fact("captains[]", {"name": captain, "role": "captain"}, fleet_url))
        photo = self.photo(card.get("photo"), fleet_url)
        if photo:
            facts.append(self.fact("photos[]", photo, fleet_url))
        link = card["link"]
        same_host = urlsplit(link).hostname == urlsplit(fleet_url).hostname
        page = self.fetch(link) if same_host else None
        if page is None:
            return self.candidate(card["name"], link, facts)
        url, root = page
        try:
            boat = _boat_page(root, url, card["name"])
        except LayoutError as error:
            self.record(error.url, "layout", error.detail)
            return self.candidate(card["name"], link, facts)
        name = boat["name"]
        facts[0] = self.fact("name", name, url, 0.95)
        facts += [self.fact("captains[]", {"name": c, "role": "captain"}, url) for c in boat["captains"]]
        for field in ("website", "length_ft", "beam_ft", "passengers_max"):
            if boat.get(field) is not None:
                facts.append(self.fact(field, boat[field], url))
        photo = self.photo(boat.get("photo"), url)
        if photo:
            facts.append(self.fact("photos[]", photo, url))
        # One offering per id: a later rate row or schedule trip that names the same offering is the same one.
        offerings: dict[tuple, Offering] = {}
        for row in boat["rates"]:
            _merge_offering(offerings, self._offering(row, url))
        scheduled: list[tuple[tuple, dict]] = []
        for trip, rows in boat["schedule"].items():
            key = _merge_offering(offerings, self._schedule_offering(trip, rows, url))
            scheduled += [(key, r) for r in rows]
        departures: dict[tuple, Departure] = {}
        for key, r in scheduled:  # built last, so each departure carries its offering as merged
            departures.setdefault((key, r["date"], r["departs"]), Departure(
                offerings[key], r["date"], r["departs"], r["price_cents"], r["load"], url, self.times[url]))
        facts += [f for o in offerings.values() for f in o.facts]
        return self.candidate(name, link, _unique(facts), offerings=tuple(offerings.values()),
                              departures=tuple(departures.values()))

    def _offering(self, row: dict, url: str) -> Offering:
        value = {k: v for k, v in row.items() if v is not None}
        return Offering(row["name"], row["trip_type"], (self.fact("trip_types[]", value, url),),
                        price_cents=row["price_cents"], price_basis="private", capacity=row["capacity"],
                        days=row["days"], season_from=row["season_from"], season_to=row["season_to"])

    def _schedule_offering(self, name: str, rows: list[dict], url: str) -> Offering:
        loads = {r["load"] for r in rows}
        capacity = int(next(iter(loads))) if len(loads) == 1 and (next(iter(loads)) or "").isdigit() else None
        first = rows[0]
        value = {"name": name, "trip_type": trip_type(name), "price_basis": "per-person",
                 "price_cents": _modal(r["price_cents"] for r in rows), "departs_local": _modal(r["departs"] for r in rows),
                 "duration_h": first["duration_h"], "capacity": capacity}
        value = {k: v for k, v in value.items() if v is not None}
        return Offering(name, value["trip_type"], (self.fact("trip_types[]", value, url),),
                        price_cents=value.get("price_cents"), price_basis="per-person", capacity=capacity,
                        departs_local=value.get("departs_local"), duration_h=first["duration_h"])


def _offering_key(offering: Offering) -> tuple:
    """What ``Offering.id`` hashes besides the vessel id: two offerings with the same key share an id."""
    return offering_name_norm(offering.name), offering.season_from, offering.season_to


def _merge_offering(offerings: dict[tuple, Offering], offering: Offering) -> tuple:
    """Add ``offering`` under its key, merging with an offering already there; returns the key.

    The merged offering cites both sets of facts. Two different known prices for one offering id
    contradict each other, so its price becomes unknown (None) rather than whichever row came first.
    """
    key = _offering_key(offering)
    kept = offerings.get(key)
    if kept is None:
        offerings[key] = offering
        return key
    prices = {p for p in (kept.price_cents, offering.price_cents) if p is not None}
    offerings[key] = replace(kept, price_cents=prices.pop() if len(prices) == 1 else None,
                             facts=tuple(_unique([*kept.facts, *offering.facts])))
    return key


def _unique(facts: list[Fact]) -> list[Fact]:
    seen, out = set(), []
    for f in facts:
        key = (f.field, f.source_url, repr(f.value))
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


# ---- fr-fleet-php ----------------------------------------------------------------------------

def _style_url(style: str) -> str | None:
    match = re.search(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", style or "")
    return match.group(1) if match else None


def _fleet_cards(root: Node, base: str) -> list[dict]:
    cards, seen = [], set()
    for col in root.find_all(cls="feature-col"):
        title, link = col.find(cls="feature-title"), col.find("a")
        if not title or not link or not link.attrs.get("href") or not title.text():
            continue
        url = urljoin(base, link.attrs["href"]).split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        image = col.find(cls="feature-img")
        src = _style_url(image.attrs.get("style", "")) if image else None
        src = src or (col.find("img").attrs.get("src") if col.find("img") else None)
        captains = [n for line in (col.find(cls="feature-teaser") or col).lines()
                    if line.lower().startswith("captain") for n in _names(line)]
        cards.append({"name": title.text(), "link": url, "captains": captains, "photo": src})
    return cards


def _labelled(details: Node) -> dict[str, Node]:
    """Label -> value node for the boat details block (``<span class=font_bold18>Label:</span><br><span>...``)."""
    out, label = {}, None
    for node in details.iter():
        if "font_bold18" in node.classes:
            label = node.text().rstrip(":").strip().lower()
        elif label and node.tag in ("span", "b", "div") and node.classes & {"font_default14", "font_default"}:
            out.setdefault(label, node)
            label = None
    return out


def _boat_page(root: Node, url: str, fallback_name: str) -> dict:
    """A boat page's facts; ``LayoutError`` when it has none of the boat-details, rates or schedule blocks."""
    details = root.find(cls="pod_boat_details")
    has_rates = any(n.attrs.get("id") == "rates-container" for n in root.iter())
    has_trips = any("data-trip-id" in n.attrs for n in root.iter())
    if details is None and not has_rates and not has_trips:
        raise LayoutError(url, "boat page without pod_boat_details, rates-container or data-trip-id")
    heading = details.find("h2") if details else None
    name = heading.text() if heading and heading.text() else fallback_name
    labels = _labelled(details) if details else {}
    captains = _names(labels["captains"].text()) if "captains" in labels else []
    site = labels.get("boat website")
    link = site.find("a") if site else None
    image = root.find(cls="pod_boat_image")
    image = image.find("img") if image else None
    text = " ".join(root.lines(frozenset({"trip-comments", "scale-group"})))
    size, capacity = SIZE.search(text), CAPACITY.search(text)
    return {"name": name, "captains": captains,
            "website": urljoin(url, link.attrs["href"]) if link and link.attrs.get("href") else None,
            "length_ft": float(size.group(1)) if size else None, "beam_ft": float(size.group(2)) if size else None,
            "passengers_max": int(capacity.group(1)) if capacity else None,
            "photo": image.attrs.get("src") if image else None,
            "rates": _rates(root), "schedule": _schedule(root, name)}


def _row_prices(columns: list[tuple[str, str]]) -> list[tuple[str, int | None]]:
    """(day label, cents) for one rate row's price columns, chosen by header and cell label, never by position.

    Day columns ("Mon - Thu", "Fri - Sun") give one price each, merged when every day has the same one; a
    column headed Credit or Card is ignored; with payment columns ("Price", "Cash", "Credit") the cash column
    wins, else the one non-credit price. Two different unlabelled prices are ambiguous: price unknown.
    """
    days = [(label, cash_cents(cell)) for label, cell in columns if day_set(label)]
    if days:
        priced = [(label, cents) for label, cents in days if cents is not None]
        if len(priced) == len(days) and len({cents for _, cents in priced}) == 1:  # one price every day
            return [("", priced[0][1])]
        return priced
    other = [(label, cell) for label, cell in columns if not CREDIT.search(label)]
    other = [x for x in other if CASH.search(x[0])] or other
    values = {cash_cents(cell) for _, cell in other} - {None}
    if len(values) == 1:
        return [("", values.pop())]
    return [("", None)] if values else []


def _rates(root: Node) -> list[dict]:
    """The "Charter Rates" table: one private offering per row and distinct day-column price."""
    box = next((n for n in root.iter() if n.attrs.get("id") == "rates-container"), None)
    table = box.find("table") if box else None
    if table is None:
        return []
    rows = [[c.text() for c in tr.children if isinstance(c, Node) and c.tag in ("td", "th")] for tr in table.find_all("tr")]
    rows = [r for r in rows if len(r) >= 4]
    if not rows:
        return []
    header, out = rows[0], []
    for cells in rows[1:]:
        name, season = cells[0], cells[1]  # a whole-boat rate; the name keeps it apart from a same-named open trip
        name = name if "charter" in name.lower() else f"Private charter: {name}"
        months = season_range(season)
        if not months and season and not ALL_YEAR.match(season):
            name = f"{name} ({season})"
        capacity = int(cells[2]) if cells[2].isdigit() else None
        priced = _row_prices([(header[i] if i < len(header) else "", c) for i, c in enumerate(cells[3:], start=3)])
        for label, cents in priced:
            days = day_set(label) if label else None
            out.append({"name": f"{name} ({label})" if days else name, "trip_type": trip_type(cells[0]),
                        "price_cents": cents, "price_basis": "private", "capacity": capacity,
                        "season_from": months[0] if months else None, "season_to": months[1] if months else None,
                        "days": days})
    return out


def _schedule(root: Node, boat: str) -> dict[str, list[dict]]:
    """Schedule rows grouped by trip name: date, departure time, price and load; never comments or spots."""
    cells: dict[str, list[Node]] = {}
    for node in root.iter():
        trip = node.attrs.get("data-trip-id")
        if trip and not node.classes & {"scale-group"}:
            cells.setdefault(trip, []).append(node)
    out: dict[str, list[dict]] = {}
    names: dict[str, str] = {}  # normalized trip name -> the first spelling seen
    want = offering_name_norm(boat)
    for nodes in cells.values():
        def part(cls: str) -> Node | None:
            return next((n for cell in nodes for n in [cell, *cell.iter()] if cls in n.classes), None)
        info, depart, back = part("trip-info") or part("trip-name"), part("trip-depart"), part("trip-return")
        if not info or not depart:
            continue
        strong = info.find("strong")  # the boat's name; a row without one cannot be attributed to this boat
        if strong is None or offering_name_norm(strong.text()) != want:
            continue
        lines = [x for x in info.lines(frozenset({"charter-alert", "trip-icons"})) if x != strong.text()]
        if not lines or not offering_name_norm(lines[0]) or not local_date(depart.text()):
            continue
        trip = names.setdefault(offering_name_norm(lines[0]), lines[0])
        departs, returns = local_time(depart.text()), local_time(back.text()) if back else None
        duration = None
        if back and departs and returns and local_date(back.text()):
            start = datetime.fromisoformat(f"{local_date(depart.text())}T{departs}")
            duration = round((datetime.fromisoformat(f"{local_date(back.text())}T{returns}") - start).total_seconds() / 3600, 2)
        load, price = part("trip-load"), part("trip-price")
        load_text = load.text() if load else None
        out.setdefault(trip, []).append({
            "date": local_date(depart.text()), "departs": departs, "duration_h": duration if duration and duration > 0 else None,
            "price_cents": cash_cents(price.text()) if price else None,
            "load": load_text if load_text and load_text != "-" else None})
    return out


# ---- generic -----------------------------------------------------------------------------------

def _boat_links(root: Node, base: str) -> list[tuple[str, str]]:
    """(name, absolute URL) for same-host links whose path looks like a boat page; first name per URL wins."""
    host, here, out, seen = urlsplit(base).hostname, urlsplit(base).path.rstrip("/"), [], set()
    for a in root.find_all("a"):
        url = urljoin(base, a.attrs.get("href", ""))
        parts = urlsplit(url)
        name = a.text()
        if (parts.hostname != host or parts.path.rstrip("/") == here or not BOAT_PATH.search(parts.path)
                or not 2 <= len(name) <= 60 or NOT_A_NAME.match(name)):
            continue
        key = url.split("#")[0]
        if key not in seen and offering_name_norm(name) not in {offering_name_norm(n) for n, _ in out}:
            seen.add(key)
            out.append((name, key))
    return out
