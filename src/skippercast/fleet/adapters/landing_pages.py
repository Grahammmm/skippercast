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
comments, open spots or any free text. Photos are recorded as a link plus an
attribution (``photos[]`` = ``{url, attribution}``); image bytes are never
fetched. Every fetch goes through ``ctx.net`` (``FleetSession``); a refused or
failed page is skipped and listed in ``skipped``.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
import re
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import urljoin, urlsplit

from ... import http
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


# ---- a small DOM on the standard library parser --------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: Mapping[str, str], parent: "Node | None" = None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter(self) -> Iterator["Node"]:
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.iter()

    def find_all(self, tag: str | None = None, cls: str | None = None) -> list["Node"]:
        return [n for n in self.iter() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes)]

    def find(self, tag: str | None = None, cls: str | None = None) -> "Node | None":
        return next(iter(self.find_all(tag, cls)), None)

    def lines(self, skip: frozenset = frozenset()) -> list[str]:
        """Text split at <br> and block ends, whitespace collapsed; subtrees with a class in ``skip`` left out."""
        parts: list[str] = []

        def walk(node: Node) -> None:
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                elif not child.classes & skip:
                    if child.tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
                        parts.append("\n")
                    walk(child)
        walk(self)
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


def _names(text: str) -> list[str]:
    parts = re.split(r"\s*(?:&|/|,|\band\b)\s*", text.replace("Captains", "").replace("Captain", ""))
    return [p.strip(" :.") for p in parts if 2 <= len(p.strip(" :.")) <= 60]


# ---- the adapter ---------------------------------------------------------------------------

class LandingPages:
    id = ID
    kind = "discover"

    def __init__(self) -> None:
        self.skipped: list[dict] = []

    def discover(self, binding, ctx: RunContext) -> Iterable[Candidate]:
        params = binding.params
        if params.get("template") not in TEMPLATES:
            raise ValueError(f"{binding.id}: template must be one of {', '.join(TEMPLATES)}")
        landing = next((x for x in getattr(ctx.region, "landings", ()) if x.id == params.get("landing")), None)
        page = _Page(self, binding, ctx, landing)
        fleet = page.fetch(params["url"])
        if fleet is None:
            return
        url, root = fleet
        if params["template"] == "generic":
            for name, link in _boat_links(root, url):
                yield page.candidate(name, link, [page.fact("name", name, url, 0.8)])
            return
        cards = _fleet_cards(root, url) or [{"name": n, "link": link} for n, link in _boat_links(root, url)]
        for card in cards:
            yield page.boat(card, url)

    def enrich(self, vessel: Mapping[str, Any], binding, ctx: RunContext) -> Iterable[Fact]:
        return ()


class _Page:
    """One binding's run: fetching, provenance and the parsed candidates."""

    def __init__(self, adapter: LandingPages, binding, ctx: RunContext, landing):
        self.adapter, self.binding, self.ctx = adapter, binding, ctx
        self.landing_id = binding.params.get("landing")
        self.landing_name = landing.name if landing else None
        self.port = landing.port if landing else None
        self.times: dict[str, str] = {}  # page URL -> when it was fetched

    def fetch(self, url: str) -> tuple[str, Node] | None:
        from ..net import Skipped  # net imports config, which imports the adapter registry
        try:
            response = self.ctx.net.get(url)
        except Skipped as error:
            self.adapter.skipped.append(error.as_dict())
            return None
        except http.SourceError as error:
            self.adapter.skipped.append({"url": url, "reason": "error", "detail": type(error).__name__})
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
        return {"url": url, "attribution": credit} if urlsplit(url).scheme in ("http", "https") and credit else None

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
        boat = _boat_page(root, url, card["name"])
        name = boat["name"]
        facts[0] = self.fact("name", name, url, 0.95)
        facts += [self.fact("captains[]", {"name": c, "role": "captain"}, url) for c in boat["captains"]]
        for field in ("website", "length_ft", "beam_ft", "passengers_max"):
            if boat.get(field) is not None:
                facts.append(self.fact(field, boat[field], url))
        photo = self.photo(boat.get("photo"), url)
        if photo:
            facts.append(self.fact("photos[]", photo, url))
        offerings = [self._offering(row, url) for row in boat["rates"]]
        departures: list[Departure] = []
        for trip, rows in boat["schedule"].items():
            offering = self._schedule_offering(trip, rows, url)
            offerings.append(offering)
            departures += [Departure(offering, r["date"], r["departs"], r["price_cents"], r["load"], url,
                                     self.times[url]) for r in rows]
        facts += [f for o in offerings for f in o.facts]
        return self.candidate(name, url, _unique(facts), offerings=tuple(offerings), departures=tuple(departures))

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
        url = urljoin(base, link.attrs["href"])
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
    details = root.find(cls="pod_boat_details") or root
    heading = details.find("h2")
    labels = _labelled(details)
    captains = _names(labels["captains"].text()) if "captains" in labels else []
    site = labels.get("boat website")
    link = site.find("a") if site else None
    image = root.find(cls="pod_boat_image")
    image = image.find("img") if image else None
    text = " ".join(root.lines(frozenset({"trip-comments", "scale-group"})))
    size, capacity = SIZE.search(text), CAPACITY.search(text)
    return {"name": heading.text() if heading and heading.text() else fallback_name, "captains": captains,
            "website": urljoin(url, link.attrs["href"]) if link and link.attrs.get("href") else None,
            "length_ft": float(size.group(1)) if size else None, "beam_ft": float(size.group(2)) if size else None,
            "passengers_max": int(capacity.group(1)) if capacity else None,
            "photo": image.attrs.get("src") if image else None,
            "rates": _rates(root), "schedule": _schedule(root, heading.text() if heading else fallback_name)}


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
        priced = [(header[i] if i < len(header) else "", price_cents(c)) for i, c in enumerate(cells[3:], start=3)]
        priced = [(label, cents) for label, cents in priced if cents is not None]
        if len(priced) == len(cells) - 3 and len({cents for _, cents in priced}) == 1:  # one price every day
            priced = [("", priced[0][1])]
        elif any(day_set(label) is None for label, _ in priced):  # cash/credit columns: the first (base) price
            priced = priced[:1]
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
    want = offering_name_norm(boat)
    for nodes in cells.values():
        def part(cls: str) -> Node | None:
            return next((n for cell in nodes for n in [cell, *cell.iter()] if cls in n.classes), None)
        info, depart, back = part("trip-info") or part("trip-name"), part("trip-depart"), part("trip-return")
        if not info or not depart:
            continue
        strong = info.find("strong")
        lines = [x for x in info.lines(frozenset({"charter-alert", "trip-icons"})) if not strong or x != strong.text()]
        if strong and offering_name_norm(strong.text()) != want or not lines or not local_date(depart.text()):
            continue
        departs, returns = local_time(depart.text()), local_time(back.text()) if back else None
        duration = None
        if back and departs and returns and local_date(back.text()):
            start = datetime.fromisoformat(f"{local_date(depart.text())}T{departs}")
            duration = round((datetime.fromisoformat(f"{local_date(back.text())}T{returns}") - start).total_seconds() / 3600, 2)
        load, price = part("trip-load"), part("trip-price")
        load_text = load.text() if load else None
        out.setdefault(lines[0], []).append({
            "date": local_date(depart.text()), "departs": departs, "duration_h": duration if duration and duration > 0 else None,
            "price_cents": price_cents(price.text()) if price else None,
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
