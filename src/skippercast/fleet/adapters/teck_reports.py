"""``teck-reports``: boats on the TECK.net report sites (design section 6).

SoCal, San Diego and NorCal Fish Reports publish a paged boat directory
(``/charter_boats/index.php?page=N``) and one page per boat with a "Boat
Information" block. This adapter reads both and emits one ``Candidate`` per
directory card, with facts from the boat page: name, landing, city, length and
beam, year built, maximum load, bunks and the date of the latest published
count. Facts only (``rights`` from the binding, normally ``facts-only``): no
report text, images, owner or skipper names, and no phone numbers; the parsers
never read those rows.

It extends the existing TECK.net fetch rather than adding a scraper beside it
(design, "Relationship to the existing reports pipeline"): pages are read with
``pipeline.collect``'s ``Client`` over the run's ``FleetSession`` (allowlist,
off-limits deny, robots.txt, per-host interval and budget) and through
``collect.http_cache()``, the conditional-GET cache the daily dock-totals jobs
use. There is no second TECK.net client or cache directory.

A page whose structure changed raises ``LayoutError`` instead of yielding
nothing: a directory page with no boat cards or an unreadable pager, or a boat
page without a readable "Boat Information" block. A single odd boat page is
recorded as a skip; when at least half of a site's boat pages fail, the run
raises, since that means the layout changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping
from urllib.parse import urljoin, urlsplit

from ... import http
from ...pipeline import collect
from ._html import LayoutError, Node, parse
from .base import Candidate, Fact, RunContext

if TYPE_CHECKING:
    from ..config import Binding, FleetRegion

__all__ = ["BoatPage", "DirectoryEntry", "DirectoryPage", "LayoutError", "TeckReports", "match_landing",
           "match_port", "parse_boat_page", "parse_directory", "teck_client"]

MAX_PAGES = 50
_PAGER = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)
_MDY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"), 1)}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")  # "Endeavor (MB)": the site's disambiguator, not the vessel name


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    url: str
    landing: str | None


@dataclass(frozen=True)
class DirectoryPage:
    url: str
    entries: tuple[DirectoryEntry, ...]
    page: int
    pages: int
    next_url: str | None


@dataclass(frozen=True)
class BoatPage:
    url: str
    report_name: str            # as the site prints it, e.g. "Endeavor (MB)"
    name: str                   # without the site's parenthesised disambiguator
    landing: str | None
    city: str | None
    state: str | None
    length_ft: float | None
    beam_ft: float | None
    year_built: int | None
    passengers_max: int | None
    bunks: int | None
    last_report_date: str | None  # ISO date of the newest published count


# ---- parsers ------------------------------------------------------------------------

def parse_directory(markup: str, url: str) -> DirectoryPage:
    """One page of ``/charter_boats/index.php``: boat cards and the pager."""
    root = parse(markup)
    cards = root.find_all("div", cls="boat-card")
    if not cards:
        raise LayoutError(url, "no boat cards on the directory page")
    host = urlsplit(url).hostname
    entries = []
    for card in cards:
        top = card.find(cls="boat-card-top")
        link = top.find("a", where=lambda n: bool(n.attrs.get("href"))) if top else None
        name = link.text() if link else ""
        if not link or not name:
            raise LayoutError(url, "boat card without a linked boat name")
        target = urljoin(url, link.attrs["href"])
        if urlsplit(target).hostname != host:
            continue  # a card pointing off-site is not one of this site's boat pages
        bottom = card.find(cls="boat-card-bottom")
        landing = bottom.find("a", where=lambda n: "/landings/" in n.attrs.get("href", "")) if bottom else None
        entries.append(DirectoryEntry(name=name, url=target, landing=(landing.text() or None) if landing else None))
    page, pages, next_url = 1, 1, None
    pager = root.find("div", cls="pager-panel")
    if pager is not None:
        match = _PAGER.search(pager.text())
        if not match:
            raise LayoutError(url, "pager without 'Page N of M'")
        page, pages = int(match[1]), int(match[2])
        following = pager.find("a", where=lambda n: "next" in n.classes and bool(n.attrs.get("href")))
        if following is not None:
            next_url = urljoin(url, following.attrs["href"])
        elif page < pages:
            raise LayoutError(url, f"page {page} of {pages} has no next link")
    return DirectoryPage(url=url, entries=tuple(entries), page=page, pages=pages, next_url=next_url)


BOAT_ROWS = frozenset({"boat", "dimensions", "year built", "max load", "bunks"})
LANDING_ROWS = frozenset({"landing", "city", "state"})


def _block_rows(root: Node, title: str, wanted: frozenset[str]) -> dict[str, str] | None:
    """The ``wanted`` label -> value rows of the block headed ``title`` (table rows or a
    definition list); None when there is no such block. Other rows (owner, skipper,
    phone) are not read."""
    heading = root.find(where=lambda n: n.tag in ("h2", "h3", "h4") and n.text().lower() == title.lower())
    if heading is None or heading.parent is None:
        return None
    rows: dict[str, str] = {}
    container = heading.parent
    for row in container.find_all("tr"):
        cells = [c for c in row.element_children() if c.tag in ("td", "th")]
        if len(cells) >= 2 and _label(cells[0].text()) in wanted:
            rows.setdefault(_label(cells[0].text()), cells[1].text())
    for listing in container.find_all("dl"):
        label = None
        for child in listing.element_children():
            if child.tag == "dt":
                label = _label(child.text())
            elif child.tag == "dd" and label in wanted:
                rows.setdefault(label, child.text())
                label = None
    return rows


def _label(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", text.lower()).strip()


def _int(value: str | None, low: int, high: int) -> int | None:
    match = re.search(r"\d+", value or "")
    number = int(match[0]) if match else None
    return number if number is not None and low <= number <= high else None


def _dimensions(value: str | None) -> tuple[float | None, float | None]:
    numbers = [float(x) for x in _NUMBER.findall(value or "")]
    length = numbers[0] if numbers and 10 <= numbers[0] <= 400 else None
    beam = numbers[1] if length and len(numbers) > 1 and 3 <= numbers[1] < length else None
    return length, beam


def _last_report(root: Node) -> str | None:
    dates: list[date] = []
    for cell in root.find_all("td", cls="scale-data"):  # older layout: <td class="scale-data"><strong>MM-DD-YYYY
        for strong in cell.find_all("strong"):
            match = _MDY.match(strong.text())
            if match:
                dates.append(date(int(match[3]), int(match[1]), int(match[2])))
    for block in root.find_all(cls="rf-trip-date"):  # newer layout: <span class="rf-trip-day">Oct 4</span> + year
        day = block.find(cls="rf-trip-day")
        year = block.find(cls="rf-trip-yr")
        parts = (day.text() if day else "").split()
        if len(parts) == 2 and parts[0][:3].lower() in _MONTHS and parts[1].isdigit() and year and year.text().isdigit():
            dates.append(date(int(year.text()), _MONTHS[parts[0][:3].lower()], int(parts[1])))
    return max(dates).isoformat() if dates else None


def parse_boat_page(markup: str, url: str) -> BoatPage:
    """A ``/charter_boats/<boat>.php`` page: the "Boat Information" and "Landing Information" blocks.

    Only the boat, dimensions, year, load and bunks rows and the landing's name,
    city and state are read; owner, skipper and phone rows are never touched.
    """
    root = parse(markup)
    boat = _block_rows(root, "Boat Information", BOAT_ROWS)
    if boat is None:
        raise LayoutError(url, "no 'Boat Information' block")
    report_name = boat.get("boat", "")
    if not report_name:
        raise LayoutError(url, "'Boat Information' block without a Boat row")
    landing = _block_rows(root, "Landing Information", LANDING_ROWS) or {}
    city, state = landing.get("city") or None, landing.get("state") or None
    if city and re.fullmatch(r"[A-Z]{2}", city):  # a shifted row ("City: CA, State: 94585")
        city, state = None, city
    if state and not re.fullmatch(r"[A-Z]{2}", state):
        state = None
    length, beam = _dimensions(boat.get("dimensions"))
    return BoatPage(
        url=url, report_name=report_name, name=_SUFFIX.sub("", report_name).strip() or report_name,
        landing=landing.get("landing") or None, city=city, state=state, length_ft=length, beam_ft=beam,
        year_built=_int(boat.get("year built"), 1900, 2100), passengers_max=_int(boat.get("max load"), 1, 400),
        bunks=_int(boat.get("bunks"), 1, 400), last_report_date=_last_report(root))


# ---- region matching ----------------------------------------------------------------

def _norm(text: str) -> str:
    text = re.sub(r"\b(llc|inc|corp)\b\.?", " ", text.lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]+", "", text)


def match_landing(region: "FleetRegion", name: str | None) -> str | None:
    """The region landing id whose name matches ``name`` (punctuation, case and LLC/Inc ignored)."""
    key = _norm(name or "")
    hits = [x.id for x in region.landings if key and _norm(x.name) == key]
    return hits[0] if len(hits) == 1 else None


def match_port(region: "FleetRegion", place: str | None) -> str | None:
    """The region port id one of whose name parts ("Port San Luis · Avila Beach") equals ``place``."""
    key = _norm(place or "")
    hits = [p.id for p in region.ports if key and key in {_norm(part) for part in re.split(r"[·,]", p.name)}]
    return hits[0] if len(hits) == 1 else None


# ---- the adapter --------------------------------------------------------------------

def teck_client(ctx: RunContext) -> collect.Client:
    """``collect``'s Client over the run's FleetSession, reading through the collector's cache."""
    return collect.client_factory(ctx.net, cache=collect.http_cache())(ctx.clock())


def _record(ctx: RunContext, url: str, reason: str, detail: str = "") -> None:
    ctx.net.skips.append({"url": url, "reason": reason, "detail": detail[:300]})


class TeckReports:
    id = "teck-reports"
    kind = "discover"

    def directory(self, binding: "Binding", ctx: RunContext, client: collect.Client) -> Iterator[DirectoryEntry]:
        """Every boat card of the binding's directory, following the pager."""
        url: str | None = urljoin(binding.params["base"].rstrip("/") + "/", binding.params["directory"].lstrip("/"))
        seen: set[str] = set()
        while url and url not in seen:
            if len(seen) >= MAX_PAGES:
                raise LayoutError(url, f"directory pager runs past {MAX_PAGES} pages")
            seen.add(url)
            page = parse_directory(client.get(url), url)
            yield from page.entries
            url = page.next_url

    def discover(self, binding: "Binding", ctx: RunContext) -> Iterable[Candidate]:
        from ..net import Skipped  # net imports config, which imports this package's registry

        if binding.params.get("role") == "dedupe-index":
            # SportfishingReport's /landings/ index is a landing directory, not a boat directory; the
            # cross-site dedupe pass reads it in a later task.
            _record(ctx, binding.params.get("base", ""), "unsupported-role", "dedupe-index")
            return []
        client = teck_client(ctx)
        found: list[DirectoryEntry] = []
        try:
            for entry in self.directory(binding, ctx, client):
                found.append(entry)
        except Skipped:
            pass  # FleetSession recorded why (robots, off-limits, budget); keep the pages already read
        except http.SourceError as error:
            _record(ctx, binding.params["base"], "fetch-error", str(error))
        entries = list(dict.fromkeys(found))
        candidates, failed, read = [], 0, 0
        for entry in entries:
            page = None
            try:
                page = parse_boat_page(client.get(entry.url), entry.url)
                read += 1
            except Skipped:
                pass
            except LayoutError as error:
                read += 1
                failed += 1
                _record(ctx, entry.url, "layout", error.detail)
            except (http.SourceError, ValueError) as error:
                _record(ctx, entry.url, "fetch-error", str(error))
            candidates.append(self.candidate(binding, ctx, entry, page))
        if failed and failed * 2 >= read:
            raise LayoutError(binding.params["base"], f"{failed} of {read} boat pages have no readable 'Boat Information' block")
        return candidates

    def enrich(self, vessel: Mapping[str, Any], binding: "Binding", ctx: RunContext) -> Iterable[Fact]:
        return ()

    def candidate(self, binding: "Binding", ctx: RunContext, entry: DirectoryEntry,
                  page: BoatPage | None) -> Candidate:
        retrieved = ctx.clock()

        def fact(field: str, value: Any, confidence: float, url: str) -> Fact:
            return Fact(field=field, value=value, source_id=binding.id, source_url=url, method="page",
                        confidence=confidence, rights=binding.rights, retrieved_at=retrieved)

        landing_text = (page.landing if page else None) or entry.landing
        if page is None:
            name = _SUFFIX.sub("", entry.name).strip() or entry.name
            facts = [fact("name", name, 0.8, entry.url), fact("catch_reporting.report_name", entry.name, 0.8, entry.url)]
            if entry.landing:
                facts.append(fact("landing", entry.landing, 0.7, entry.url))
            port = None
        else:
            name = page.name
            facts = [fact("name", page.name, 0.9, page.url), fact("catch_reporting.report_name", page.report_name, 0.9, page.url)]
            for field, value, confidence in (
                    ("landing", landing_text, 0.8), ("port", page.city, 0.7), ("length_ft", page.length_ft, 0.7),
                    ("beam_ft", page.beam_ft, 0.7), ("year_built", page.year_built, 0.7),
                    ("passengers_max", page.passengers_max, 0.7), ("bunks", page.bunks, 0.6),
                    ("catch_reporting.last_report_date", page.last_report_date, 0.9)):
                if value is not None:
                    facts.append(fact(field, value, confidence, page.url))
            port = page.city
        landing_id = match_landing(ctx.region, landing_text)
        port_id = next((x.port for x in ctx.region.landings if x.id == landing_id), None) or match_port(ctx.region, port)
        return Candidate(source_id=binding.id, name=name, port_hint=port_id, landing_hint=landing_id, facts=tuple(facts))
