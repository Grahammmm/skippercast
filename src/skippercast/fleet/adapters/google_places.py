"""``google-places``: Google ``place_id`` per vessel from the Places API (New) (design section 6).

Caching rule (re-read for CF-16 on 2026-10-05; docs/legal/data-rights-register.md):

- Places API policies (page last updated 2026-09-28): "You must not pre-fetch,
  cache, or store Places API content beyond the allowed exceptions, although
  the place_id is exempt from caching restrictions." ... "You can therefore
  store place ID values indefinitely."
- Maps Service Specific Terms § 14.3 (last modified 2026-06-10): "Customer may
  temporarily cache latitude and longitude values from the Places API for up
  to 30 consecutive calendar days, after which Customer must delete the cached
  latitude and longitude values."

No other Places field (rating, review count, business status, name, phone,
website) may be stored. So this adapter emits one fact, ``place_id``, and uses
everything else in a response only in memory, to pick the place:

- **Text Search** once per port that has vessels (``POST places:searchText``
  with ``"<query> <port name>, <region>"`` biased to a circle around the port,
  field mask ``places.id,places.displayName,places.businessStatus``). A place
  is matched to a vessel of that port when the vessel's normalised name occurs
  in the place's display name on word boundaries (``name_in_label``: "Sea Wolf"
  matches "SeaWolf Sportfishing", "Wolf" does not) and the match is one-to-one;
  closed places and ambiguous matches are skipped and counted.
- **Place Details** with field mask ``id`` (the IDs-only refresh Google
  recommends for stored place IDs) for a vessel that already has a
  ``place_id``: a moved ID is recorded as the new value; a ``NOT_FOUND`` is
  counted in the report.

``places_purge_ops`` is the retention operation: ``fact.purge`` deletes every
``google-places`` fact except ``place_id`` (and latitude/longitude for 30 days),
so any Places content stored by mistake, or under an earlier reading of the
terms, is gone at the next ``enrich-code`` run.

The key comes from ``GOOGLE_PLACES_API_KEY``. Without it the adapter makes no
request and reports ``{"status": "skipped", "reason": ...}``. The key travels in
the ``X-Goog-Api-Key`` header, never in a URL, and responses are never cached
on disk.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Any, Callable, Iterable, Mapping, Protocol

from ... import http
from .base import Fact, RunContext

ID = "google-places"
ENV_KEY = "GOOGLE_PLACES_API_KEY"
API = "https://places.googleapis.com/v1"
API_HOST = "places.googleapis.com"
SEARCH_MASK = "places.id,places.displayName,places.businessStatus,nextPageToken"
DETAILS_MASK = "id"
CONFIDENCE = 0.85
MIN_NAME = 4               # a shorter normalised vessel name matches too much
SEARCH_RADIUS_M = 20000.0
PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{10,300}$")

# Fields a google-places fact may hold and for how long (days; None = indefinitely). Anything else: not at all.
CACHE_DAYS: Mapping[str, int | None] = {"place_id": None, "location.latitude": 30, "location.longitude": 30}


def place_url(place_id: str) -> str:
    """The Google Maps link for a place: the fact's source_url and the attribution link where it is shown."""
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def norm(text: str) -> str:
    """The fleet name screen rule (design section 7): upper case, A-Z and 0-9 only."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def name_in_label(name: str, label: str) -> bool:
    """Whether normalised ``name`` occurs in ``label`` starting and ending on word boundaries.

    The label's words are joined as ``norm`` joins them, so spacing may differ
    ("SEAWOLF" matches "Sea Wolf Charters"), but the name may not start or end
    inside a word ("WOLF" does not match "SeaWolf", nor "ANNA" "Savannah").
    """
    words = [w for w in re.split(r"[^A-Z0-9]+", re.sub(r"['\u2019]", "", (label or "").upper())) if w]
    if not name or not words:
        return False
    starts, ends, offset = set(), set(), 0
    for word in words:
        starts.add(offset)
        offset += len(word)
        ends.add(offset)
    joined = "".join(words)
    at = joined.find(name)
    while at != -1:
        if at in starts and at + len(name) in ends:
            return True
        at = joined.find(name, at + 1)
    return False


def places_purge_ops(now: str) -> list[dict]:
    """``fact.purge`` operations enforcing CACHE_DAYS at ``now`` (ISO UTC): one per retention period."""
    moment = datetime.strptime(now[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    ops = []
    for days in sorted({0, *(d for d in CACHE_DAYS.values() if d is not None)}):
        keep = sorted(f for f, d in CACHE_DAYS.items() if d is None or d > days)
        before = (moment - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ops.append({"op": "fact.purge", "source_id": ID, "keep_fields": keep, "seen_before": before})
    return ops


class PlacesError(Exception):
    pass


class PlacesTransport(Protocol):
    def search_text(self, body: Mapping[str, Any], field_mask: str) -> dict: ...

    def details(self, place_id: str, field_mask: str) -> dict | None: ...  # None: NOT_FOUND


class HttpPlacesTransport:
    """The Places API (New) over ``skippercast.http.Session``: one host, key in a header, nothing cached."""

    def __init__(self, api_key: str, session: http.Session | None = None):
        self.api_key = api_key
        self.session = session or http.Session(allowed_hosts={API_HOST}, attempts=3)

    def _headers(self, field_mask: str) -> dict:
        return {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": field_mask, "Accept": "application/json"}

    def search_text(self, body, field_mask):
        data = json.dumps(dict(body), sort_keys=True).encode("utf-8")
        headers = {**self._headers(field_mask), "Content-Type": "application/json"}
        response = self.session.post(f"{API}/places:searchText", data, headers=headers, use_cache=False,
                                     allowed_hosts={API_HOST})
        return response.json()

    def details(self, place_id, field_mask):
        if not PLACE_ID.match(place_id):
            raise PlacesError("not a place id")
        response = self.session.get(f"{API}/places/{place_id}", headers=self._headers(field_mask), use_cache=False,
                                    allowed_hosts={API_HOST}, raise_for_status=False)
        if response.status == 404:
            return None
        if not 200 <= response.status < 300:
            raise PlacesError(f"HTTP {response.status} from Place Details")
        return response.json()


class GooglePlaces:
    id = ID
    kind = "enrich"

    def __init__(self, transport: PlacesTransport | None = None, environ: Mapping[str, str] | None = None,
                 transport_factory: Callable[[str], PlacesTransport] = HttpPlacesTransport):
        key = (os.environ if environ is None else environ).get(ENV_KEY, "").strip()
        self.transport = transport if transport is not None else (transport_factory(key) if key else None)
        self.requests = 0
        self._ports: dict[str, dict[str, str]] = {}   # port id -> {vessel id: place id}
        self.report: dict[str, Any] = (
            {"status": "ok", "searches": 0, "details": 0, "matched": 0, "refreshed": 0, "not_found": 0,
             "ambiguous": 0, "closed": 0, "errors": 0}
            if self.transport is not None else
            {"status": "skipped", "reason": f"{ENV_KEY} is not set; no Places request was made"})

    @property
    def available(self) -> bool:
        return self.transport is not None

    def discover(self, binding, ctx: RunContext):
        return iter(())

    def _budget(self, binding) -> bool:
        if self.requests >= int(binding.params.get("max_requests", 200)):
            self.report["budget_exhausted"] = True
            return False
        self.requests += 1
        return True

    def prepare(self, vessels: Iterable[Mapping[str, Any]], binding, ctx: RunContext) -> None:
        """Run one Text Search per port that has vessels without a place_id, and match places to them."""
        if not self.available:
            return
        by_port: dict[str, list[Mapping[str, Any]]] = {}
        for vessel in vessels:
            if not vessel.get("place_id") and vessel.get("port_id") and len(norm(vessel.get("name", ""))) >= MIN_NAME:
                by_port.setdefault(vessel["port_id"], []).append(vessel)
        for port_id in sorted(by_port):
            self._ports[port_id] = self._match(port_id, by_port[port_id], binding, ctx)

    def _search(self, port, binding, ctx: RunContext) -> list[dict]:
        place = port.name.split("·")[0].strip()   # "Port San Luis · Avila Beach" -> "Port San Luis"
        query = f"{binding.params.get('query', 'fishing charter')} {place}, {ctx.region.name}"
        body: dict[str, Any] = {"textQuery": query, "pageSize": 20, "locationBias": {"circle": {
            "center": {"latitude": port.point[0], "longitude": port.point[1]}, "radius": SEARCH_RADIUS_M}}}
        places: list[dict] = []
        for _page in range(int(binding.params.get("max_pages", 3))):
            if not self._budget(binding):
                break
            result = self.transport.search_text(body, SEARCH_MASK)
            self.report["searches"] += 1
            places += [p for p in result.get("places") or [] if isinstance(p, dict)]
            token = result.get("nextPageToken")
            if not token:
                break
            body = {**body, "pageToken": token}
        return places

    def _match(self, port_id: str, vessels: list[Mapping[str, Any]], binding, ctx: RunContext) -> dict[str, str]:
        try:
            port = ctx.region.port(port_id)
        except KeyError:
            return {}
        try:
            places = self._search(port, binding, ctx)
        except (http.SourceError, OSError, ValueError, PlacesError):
            self.report["errors"] += 1
            return {}
        names = {v["vessel_id"]: norm(v.get("name", "")) for v in vessels}
        place_to: dict[str, set[str]] = {}
        vessel_to: dict[str, set[str]] = {}
        for place in places:
            pid = place.get("id")
            label = (place.get("displayName") or {}).get("text", "") if isinstance(place.get("displayName"), dict) else ""
            if not isinstance(pid, str) or not PLACE_ID.match(pid) or not isinstance(label, str) or not norm(label):
                continue
            if place.get("businessStatus") == "CLOSED_PERMANENTLY":
                self.report["closed"] += 1
                continue
            for vessel_id, name in names.items():
                if name_in_label(name, label):
                    place_to.setdefault(pid, set()).add(vessel_id)
                    vessel_to.setdefault(vessel_id, set()).add(pid)
        matched = {}
        for vessel_id, pids in vessel_to.items():
            pid = next(iter(pids))
            if len(pids) == 1 and place_to[pid] == {vessel_id}:
                matched[vessel_id] = pid
            else:
                self.report["ambiguous"] += 1
        self.report["matched"] += len(matched)
        return matched

    def enrich(self, vessel: Mapping[str, Any], binding, ctx: RunContext) -> list[Fact]:
        """The vessel's place_id fact: refreshed by Details if stored, else from prepare()'s port search."""
        if not self.available:
            return []
        vessel_id, stored = vessel["vessel_id"], vessel.get("place_id")
        place_id = None
        if isinstance(stored, str) and stored:
            if not self._budget(binding):
                return []
            try:
                result = self.transport.details(stored, DETAILS_MASK)
            except (http.SourceError, OSError, ValueError, PlacesError):
                self.report["errors"] += 1
                return []
            self.report["details"] += 1
            if result is None:
                self.report["not_found"] += 1
                return []
            place_id = result.get("id") if isinstance(result.get("id"), str) else None
            if place_id:
                self.report["refreshed"] += 1
        else:  # matched by prepare(), which searched each port once for all of its vessels
            place_id = self._ports.get(vessel.get("port_id"), {}).get(vessel_id)
        if not place_id or not PLACE_ID.match(place_id):
            return []
        return [Fact("place_id", place_id, ID, place_url(place_id), "api", CONFIDENCE, binding.rights, ctx.clock())]
