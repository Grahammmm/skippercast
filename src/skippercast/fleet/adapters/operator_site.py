"""``operator-site``: business contact facts from an operator's own website (design section 6).

For each vessel with a ``website`` fact the adapter reads at most ``max_pages``
pages (never more than 6) of that one site through the fleet session, after
adding the site's host (and its ``www.`` twin) with ``FleetSession.allow_host``.
The homepage comes first; further pages are same-site links ranked by how
likely they hold contact or booking details (contact, book, about, rates...).

From each page it extracts, as ``page`` facts whose ``source_url`` is that page:

- ``phone_business`` (NANP, E.164) from ``tel:`` links and the page text;
- ``email_business`` from ``mailto:`` links and the page text. A webmail address
  (``profile.WEBMAIL_DOMAINS``) is kept, because the operator published it as
  the business contact, but at low confidence and flagged for review;
- ``booking_platform`` (a key such as ``fareharbor``) from links, scripts and
  frames on a known booking host, and ``booking_url`` from the first such link;
- ``social.<network>.url`` and ``social.<network>.handle`` for Instagram,
  Facebook, YouTube and TikTok links;
- ``photos[]`` as ``{"url", "attribution"}`` from ``og:image`` (a link; no image
  bytes are fetched).

Links to other hosts are values, never fetched: the crawl follows same-site
links only. That is how a URL on an off-limits host (decision D7, e.g. a
FareHarbor booking link or an Instagram profile) is stored, with the operator
page as its ``source_url``. A website that is itself on an off-limits host is
never allow-listed; the session refuses it and records the skip.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urldefrag, urljoin, urlsplit

from ... import http
from ..net import Skipped
from ..ops import EMAIL
from ..profile import WEBMAIL_DOMAINS
from .base import Fact, RunContext

ID = "operator-site"
MAX_PAGES = 6
MAX_PAGE_BYTES = 2_000_000
MAX_PHONES = 3
WEBMAIL_FLAG = "email_business: webmail address; confirm it is published as the business contact"

# Booking hosts (a host covers its subdomains) and the platform key stored for them.
BOOKING_PLATFORMS = {
    "fareharbor.com": "fareharbor", "xola.com": "xola", "fishingbooker.com": "fishingbooker",
    "peek.com": "peek", "checkfront.com": "checkfront", "bookeo.com": "bookeo", "rezdy.com": "rezdy",
    "resova.com": "resova", "resova.us": "resova", "tripworks.com": "tripworks", "zaui.net": "zaui",
    "trekksoft.com": "trekksoft", "square.site": "square", "squareup.com": "square",
}
SOCIAL = {
    "instagram.com": "instagram", "facebook.com": "facebook", "fb.com": "facebook",
    "youtube.com": "youtube", "youtu.be": "youtube", "tiktok.com": "tiktok",
}
INSTAGRAM_RESERVED = {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "about", "developer", "legal"}
FACEBOOK_RESERVED = {"sharer", "sharer.php", "share", "share.php", "dialog", "plugins", "tr", "profile.php", "pages",
                     "groups", "events", "watch", "login", "help", "policies", "people", "photo.php", "story.php"}
SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".mp4", ".mov", ".doc",
                   ".docx", ".xls", ".xlsx", ".ics", ".css", ".js", ".xml", ".json")
LINK_WORDS = (("contact", 5), ("book", 4), ("reserv", 4), ("about", 3), ("charter", 2), ("trip", 2), ("rate", 2),
              ("price", 2), ("fleet", 2), ("boat", 2), ("schedule", 2))
PHONE = re.compile(r"(?<![\d+])(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?([2-9]\d{2})[\s.\-]?(\d{4})(?!\d)")
EMAIL_TEXT = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}\b")
NOT_EMAIL_TLDS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js"}
HANDLE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _under(host: str, table: Mapping[str, str]) -> str | None:
    for suffix, value in table.items():
        if host == suffix or host.endswith("." + suffix):
            return value
    return None


def _twin(host: str) -> str:
    return host[4:] if host.startswith("www.") else "www." + host


def phone_e164(text: str) -> str | None:
    """A NANP number in E.164 (``+1NXXNXXXXXX``), or None."""
    match = PHONE.fullmatch(text.strip()) or PHONE.search(text)
    return f"+1{match.group(1)}{match.group(2)}{match.group(3)}" if match else None


def clean_email(text: str) -> str | None:
    value = text.strip().split("?", 1)[0].strip().lower()
    if not EMAIL.fullmatch(value) or value.rpartition(".")[2] in NOT_EMAIL_TLDS:
        return None
    return value


class _Page(HTMLParser):
    """Anchors, frames, scripts, og:image and the visible text of one HTML page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []   # (href, anchor text)
        self.embeds: list[str] = []              # script and iframe src
        self.og_image: str | None = None
        self.text: list[str] = []
        self._hidden = 0
        self._anchor: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag, attrs):
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("script", "style", "noscript", "template"):
            self._hidden += 1
        if tag in ("script", "iframe") and attr.get("src"):
            self.embeds.append(attr["src"])
        elif tag == "a" and attr.get("href"):
            self._anchor, self._href = [], attr["href"]
        elif tag == "meta" and attr.get("property", attr.get("name", "")).lower() == "og:image" and attr.get("content"):
            self.og_image = self.og_image or attr["content"]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._hidden:
            self._hidden -= 1
        elif tag == "a" and self._anchor is not None:
            self.links.append((self._href, " ".join("".join(self._anchor).split())))
            self._anchor = None

    def handle_data(self, data):
        if self._hidden:
            return
        self.text.append(data)
        if self._anchor is not None:
            self._anchor.append(data)


@dataclass
class _Found:
    """Facts found on one site, keyed by (field, value) so a value seen on several pages is kept once."""
    best: dict[tuple[str, str], tuple[float, int, str, Any, tuple[str, ...]]] = field(default_factory=dict)
    order: int = 0

    def add(self, field_: str, value: Any, page: str, confidence: float, flags: tuple[str, ...] = ()) -> None:
        key = (field_, repr(value))
        self.order += 1
        current = self.best.get(key)
        if current is None or confidence > current[0]:
            self.best[key] = (confidence, current[1] if current else self.order, page, value, flags)


class OperatorSite:
    id = ID
    kind = "enrich"

    def __init__(self):
        self._sites: dict[str, list[tuple[str, Any, str, float, tuple[str, ...]]]] = {}
        self.report: dict[str, Any] = {"sites": 0, "pages": 0, "refused": 0, "errors": 0}

    def discover(self, binding, ctx: RunContext):
        return iter(())

    def enrich(self, vessel: Mapping[str, Any], binding, ctx: RunContext) -> Iterable[Fact]:
        website = vessel.get("website")
        if not isinstance(website, str) or not website.startswith("https://") or not _host(website):
            return []
        start = urldefrag(website)[0]
        if start not in self._sites:
            pages = min(int(binding.params.get("max_pages", MAX_PAGES)), MAX_PAGES)
            self._sites[start] = self._crawl(start, max(1, pages), ctx)
        now = ctx.clock()
        return [Fact(field_, value, binding.id, page, "page", confidence, binding.rights, now, flags)
                for field_, value, page, confidence, flags in self._sites[start]]

    # -- crawling

    def _crawl(self, start: str, max_pages: int, ctx: RunContext):
        self.report["sites"] += 1
        host = _host(start)
        site = {host, _twin(host)}
        if not ctx.region.is_off_limits(start):  # an off-limits website is never allow-listed; get() refuses it
            for name in site:
                ctx.net.allow_host(name)
        found, queue, seen, fetched = _Found(), [start], {start}, 0
        labels: dict[str, str] = {}
        while queue and fetched < max_pages:
            url = queue.pop(0)
            fetched += 1
            try:
                response = ctx.net.get(url, max_bytes=MAX_PAGE_BYTES)
            except Skipped:
                self.report["refused"] += 1
                continue
            except (http.SourceError, OSError):
                self.report["errors"] += 1
                continue
            self.report["pages"] += 1
            page_url = urldefrag(response.final_url or url)[0]
            content_type = (response.headers.get("Content-Type") or "text/html").lower()
            if "html" not in content_type:
                continue
            parsed = _Page()
            parsed.feed((response.body or b"").decode("utf-8", "replace"))
            parsed.close()
            self._extract(parsed, page_url, found)
            for link, label in self._next_links(parsed, page_url, site):
                if link not in seen:
                    seen.add(link)
                    queue.append(link)
                    labels[link] = labels.get(link, "") + " " + label.lower()
            queue.sort(key=lambda u: -sum(w for word, w in LINK_WORDS if word in u.lower() + labels.get(u, "")))
        out, phones = [], 0
        for (field_, _value), (confidence, _order, page, value, flags) in sorted(found.best.items(), key=lambda kv: kv[1][1]):
            if field_ == "phone_business":
                phones += 1
                if phones > MAX_PHONES:  # a business line or two; a page of numbers is a directory, not contacts
                    continue
            out.append((field_, value, page, confidence, flags))
        return out

    @staticmethod
    def _next_links(parsed: _Page, page_url: str, site: set[str]) -> list[tuple[str, str]]:
        """Same-site HTML links on the page as (url, anchor text); other hosts are values, never fetched."""
        links = []
        for href, label in parsed.links:
            if href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            url = urldefrag(urljoin(page_url, href))[0]
            parts = urlsplit(url)
            if parts.scheme != "https" or (parts.hostname or "").lower() not in site:
                continue
            if parts.path.lower().endswith(SKIP_EXTENSIONS):
                continue
            links.append((url, label))
        return links

    # -- extraction

    def _extract(self, parsed: _Page, page: str, found: _Found) -> None:
        for href, _label in parsed.links:
            lowered = href.strip().lower()
            if lowered.startswith("tel:"):
                phone = phone_e164(href.strip()[4:])
                if phone:
                    found.add("phone_business", phone, page, 0.8)
            elif lowered.startswith("mailto:"):
                self._email(href.strip()[7:], page, found, 0.8)
            else:
                self._external(urljoin(page, href.strip()), page, found)
        for src in parsed.embeds:
            url = urljoin(page, src.strip())
            platform = _under(_host(url), BOOKING_PLATFORMS)
            if platform:
                found.add("booking_platform", platform, page, 0.7)
        text = " ".join(" ".join(parsed.text).split())
        for match in PHONE.finditer(text):
            found.add("phone_business", f"+1{match.group(1)}{match.group(2)}{match.group(3)}", page, 0.7)
        for match in EMAIL_TEXT.finditer(text):
            self._email(match.group(0), page, found, 0.7)
        if parsed.og_image:
            image = urljoin(page, parsed.og_image.strip())
            if image.startswith("https://") and _host(image):
                found.add("photos[]", {"url": image, "attribution": _host(page)}, page, 0.6)

    @staticmethod
    def _email(text: str, page: str, found: _Found, confidence: float) -> None:
        email = clean_email(text)
        if not email:
            return
        if email.rpartition("@")[2] in WEBMAIL_DOMAINS:
            found.add("email_business", email, page, 0.5, (WEBMAIL_FLAG,))
        else:
            found.add("email_business", email, page, confidence)

    @staticmethod
    def _external(url: str, page: str, found: _Found) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return
        host = (parts.hostname or "").lower()
        platform = _under(host, BOOKING_PLATFORMS)
        if platform:
            found.add("booking_platform", platform, page, 0.8)
            found.add("booking_url", urldefrag(url)[0], page, 0.8)
            return
        network = _under(host, SOCIAL)
        if not network:
            return
        segments = [s for s in parts.path.split("/") if s]
        handle = None
        if network == "instagram" and segments and HANDLE.match(segments[0]) and segments[0].lower() not in INSTAGRAM_RESERVED:
            handle = segments[0].lower()
            url = f"https://www.instagram.com/{handle}/"
        elif network == "facebook" and segments and segments[0].lower() not in FACEBOOK_RESERVED \
                and re.fullmatch(r"[A-Za-z0-9.\-]{2,80}", segments[0]):
            handle = segments[0]
            url = f"https://www.facebook.com/{handle}/"
        elif network in ("tiktok", "youtube") and segments and segments[0].startswith("@") \
                and HANDLE.match(segments[0][1:]):
            handle = segments[0][1:].lower()
            url = f"https://www.{'tiktok' if network == 'tiktok' else 'youtube'}.com/@{handle}"
        elif network in ("instagram", "facebook", "tiktok") or not segments:
            return  # a share, post or login link, not the operator's account
        else:
            url = f"https://{host}{parts.path}"
        found.add(f"social.{network}.url", url, page, 0.8)
        if handle:
            found.add(f"social.{network}.handle", handle, page, 0.8)
