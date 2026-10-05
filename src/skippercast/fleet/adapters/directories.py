"""``directories``: association and harbor seed lists (design section 6).

A binding names one list template in ``params.list``:

- ``ggfa``: the Golden Gate Fishermen's Association charter-boat page, grouped by
  port headings. Each entry gives a vessel name and its port; the skipper names
  and mobile numbers printed with them are never read.
- ``sac``: the Sportfishing Association of California member list. It names
  member *landings* (with a link to each landing's site and its place), not
  boats, so it yields no vessel candidates; ``landing_seeds`` returns it for
  landing coverage checks.

Other list templates in a region file (``long-range-portal``, ``harbor``) are
recorded as an ``unsupported-list`` skip until their parser exists. Facts only:
vessel and port, no personal names, phones or text. A list whose structure
changed raises ``LayoutError`` rather than returning nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from ... import http
from ._html import LayoutError, parse
from .base import Candidate, Fact, RunContext
from .teck_reports import match_port

if TYPE_CHECKING:
    from ..config import Binding

__all__ = ["Directories", "LandingSeed", "VesselSeed", "parse_ggfa", "parse_sac", "LayoutError"]


@dataclass(frozen=True)
class VesselSeed:
    name: str
    port: str          # the list's port heading, as published


@dataclass(frozen=True)
class LandingSeed:
    name: str
    place: str | None  # the town after " - " in the label, when given
    url: str           # the landing's own site, as linked


def parse_ggfa(markup: str, url: str) -> tuple[VesselSeed, ...]:
    """Vessel entries (``<b><i>Name</i></b>``) under their port headings (``<h3>``)."""
    root = parse(markup)
    seeds, port = [], None
    for node in root.iter():
        if node.tag == "h3":
            port = node.text() or None
        elif node.tag == "b" and node.find("i") is not None:
            name = node.find("i").text()
            if not name:
                continue
            if port is None:
                raise LayoutError(url, "vessel entry before any port heading")
            seeds.append(VesselSeed(name=name, port=port))
    if not seeds:
        raise LayoutError(url, "no vessel entries under port headings")
    return tuple(dict.fromkeys(seeds))


def parse_sac(markup: str, url: str) -> tuple[LandingSeed, ...]:
    """Member landings: the page's button links labelled "Landing - Place"."""
    root = parse(markup)
    seeds = []
    for link in root.find_all("a", where=lambda n: "wixui-button" in n.classes and bool(n.attrs.get("href"))):
        label_node = link.find(cls="wixui-button__label")
        label = (label_node.text() if label_node else "") or link.attrs.get("aria-label", "").strip()
        if not label:
            continue
        name, _, place = label.partition(" - ")
        seeds.append(LandingSeed(name=name.strip(), place=place.strip() or None, url=link.attrs["href"]))
    if not seeds:
        raise LayoutError(url, "no member landing links")
    return tuple(dict.fromkeys(seeds))


VESSEL_LISTS = {"ggfa": parse_ggfa}
LANDING_LISTS = {"sac": parse_sac}


class Directories:
    id = "directories"
    kind = "discover"

    def _fetch(self, binding: "Binding", ctx: RunContext) -> str | None:
        from ..net import Skipped  # net imports config, which imports this package's registry

        url = binding.params["url"]
        try:
            return ctx.net.get(url).body.decode("utf-8", "replace")
        except Skipped:
            return None  # FleetSession recorded why
        except http.SourceError as error:
            ctx.net.skips.append({"url": url, "reason": "fetch-error", "detail": str(error)[:300]})
            return None

    def discover(self, binding: "Binding", ctx: RunContext) -> Iterable[Candidate]:
        kind, url = binding.params.get("list"), binding.params["url"]
        if kind in LANDING_LISTS:
            return []
        if kind not in VESSEL_LISTS:
            ctx.net.skips.append({"url": url, "reason": "unsupported-list", "detail": str(kind)})
            return []
        markup = self._fetch(binding, ctx)
        if markup is None:
            return []
        retrieved = ctx.clock()

        def fact(field: str, value: Any, confidence: float) -> Fact:
            return Fact(field=field, value=value, source_id=binding.id, source_url=url, method="page",
                        confidence=confidence, rights=binding.rights, retrieved_at=retrieved)

        return [Candidate(source_id=binding.id, name=seed.name, port_hint=match_port(ctx.region, seed.port),
                          facts=(fact("name", seed.name, 0.7), fact("port", seed.port, 0.6)))
                for seed in VESSEL_LISTS[kind](markup, url)]

    def landing_seeds(self, binding: "Binding", ctx: RunContext) -> tuple[LandingSeed, ...]:
        kind = binding.params.get("list")
        if kind not in LANDING_LISTS:
            return ()
        markup = self._fetch(binding, ctx)
        return LANDING_LISTS[kind](markup, binding.params["url"]) if markup is not None else ()

    def enrich(self, vessel: Mapping[str, Any], binding: "Binding", ctx: RunContext) -> Iterable[Fact]:
        return ()
