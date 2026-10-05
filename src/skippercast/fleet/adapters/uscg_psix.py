"""USCG Port State Information Exchange (design section 6, adapter ``uscg-psix``).

PSIX's public export page (``PSIXExportSearch.aspx``) is an ASP.NET form. Per
bound sector the adapter:

1. GETs the form and reads its hidden state and option lists;
2. POSTs a search for the sector ("Originating Unit") and the vessel type
   (``service``: ``passenger`` means "Passenger (Inspected)") over the last
   ``lookback_years`` (default 3);
3. POSTs the result page's Export button, which returns an XLSX workbook;
4. reads its ``PSIXInspections`` sheet and folds the inspections into one
   ``Candidate`` per vessel (MISLE vessel id): name, U.S. official number,
   call sign, IMO number, build year, gross tonnage, service, sectors and the
   latest inspection date.

Rows whose vessel type is not the bound service, and vessels whose latest flag
is not the United States, are dropped (charter boats are U.S.-flagged; the
sector's inspections include foreign cruise ships). The inspections sheet holds
no owner or person names. That is three requests per sector.

The PSIX XML web service (``PSIXData.asmx``) has no sector filter and needs SOAP,
so the export is the sector query. A changed form or workbook raises
``PsixFormatError``; a refused request (robots, budget) is a recorded skip.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import html
import io
import re
from typing import Iterable, Iterator
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
import zipfile

from .base import Candidate, Fact, RunContext

__all__ = ["UscgPsix", "PsixFormatError", "SERVICES", "parse_form", "parse_inspections", "vessels",
           "vessel_url"]

ID = "uscg-psix"
DEFAULT_URL = "https://cgmix.uscg.mil/XML/PSIXExportSearch.aspx"
VESSEL_URL = "https://cgmix.uscg.mil/PSIX/PSIXDetails.aspx?VesselID={id}"
SERVICES = {"passenger": "Passenger (Inspected)"}
SHEET = "PSIXInspections"
US_FLAG = "UNITED STATES"
MAX_BYTES = 50_000_000
MAX_MEMBER = 100_000_000  # largest uncompressed workbook part read (zip bomb guard)
FORM_TYPE = "application/x-www-form-urlencoded"
# Columns the inspections sheet must have (the export's header names).
COLUMNS = {"vessel_id": "MISLE Vessel Id", "name": "Vessel Name", "official": "U.S. Official Number",
           "imo": "IMO Number", "call_sign": "Vessel Call Sign", "vessel_class": "Vessel Class",
           "vessel_type": "Vessel Type", "tonnage": "Tonnage Information", "built": "Build Year",
           "flag": "Flag at Time of Activity", "unit": "Originating Unit", "started": "Activity Start Date"}
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class PsixFormatError(ValueError):
    """The PSIX form, result page or workbook is not laid out as this adapter expects."""


def vessel_url(vessel_id: str) -> str:
    return VESSEL_URL.format(id=vessel_id)


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", html.unescape(text).upper())


# ---- the ASP.NET form ------------------------------------------------------------------

@dataclass
class Form:
    hidden: dict[str, str] = field(default_factory=dict)
    selects: dict[str, dict[str, str]] = field(default_factory=dict)  # name -> normalised label -> value
    radios: dict[str, str] = field(default_factory=dict)              # name -> checked value
    texts: dict[str, str] = field(default_factory=dict)
    submits: dict[str, str] = field(default_factory=dict)


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf'\b{name}="([^"]*)"', tag)
    return html.unescape(match.group(1)) if match else None


def parse_form(page: str) -> Form:
    form = Form()
    for tag in re.findall(r"<input\b[^>]*>", page, re.I):
        name, kind = _attr(tag, "name"), (_attr(tag, "type") or "text").lower()
        if not name:
            continue
        value = _attr(tag, "value") or ""
        if kind == "hidden":
            form.hidden[name] = value
        elif kind == "radio" and re.search(r"\bchecked\b", tag):
            form.radios[name] = value
        elif kind == "text":
            form.texts[name] = value
        elif kind == "submit":
            form.submits[name] = value
    for name, body in re.findall(r'<select\b[^>]*\bname="([^"]+)"[^>]*>(.*?)</select>', page, re.I | re.S):
        options = re.findall(r'<option\b[^>]*\bvalue="([^"]*)"[^>]*>([^<]*)', body, re.I)
        form.selects[name] = {_norm(label): html.unescape(value) for value, label in options}
    if "__VIEWSTATE" not in form.hidden:
        raise PsixFormatError("PSIX page has no __VIEWSTATE")
    return form


def _option(form: Form, select: str, label: str) -> str:
    options = form.selects.get(select)
    if options is None:
        raise PsixFormatError(f"PSIX form has no {select}")
    for key in (_norm(label), _norm("Sector " + label)):
        if key in options:
            return options[key]
    raise PsixFormatError(f"PSIX {select} has no option {label!r}")


def search_fields(form: Form, sector: str, service: str, since: date, until: date) -> list[tuple[str, str]]:
    for name in ("TextBoxFromDate", "TextBoxToDate"):
        if name not in form.texts:
            raise PsixFormatError(f"PSIX form has no {name}")
    if "ButtonSearch" not in form.submits:
        raise PsixFormatError("PSIX form has no ButtonSearch")
    chosen = {"DropDownListOriginalUnit": _option(form, "DropDownListOriginalUnit", sector),
              "DropDownListVesselType": _option(form, "DropDownListVesselType", service)}
    fields = list(form.hidden.items()) + list(form.radios.items())
    fields += [("TextBoxFromDate", since.strftime("%m/%d/%Y")), ("TextBoxToDate", until.strftime("%m/%d/%Y")),
               ("ButtonSearch", form.submits["ButtonSearch"])]
    fields += [(name, chosen.get(name, "ALL")) for name in form.selects]
    return fields


def export_fields(form: Form) -> list[tuple[str, str]]:
    if "ButtonExportExcel" not in form.submits:
        raise PsixFormatError("PSIX result page has no ButtonExportExcel")
    return list(form.hidden.items()) + [("ButtonExportExcel", form.submits["ButtonExportExcel"])]


# ---- the XLSX workbook (standard library only) -----------------------------------------

def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(NS + "t"))
    value = cell.find(NS + "v")
    if value is None or value.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(value.text)]
        except (ValueError, IndexError):
            raise PsixFormatError("PSIX workbook cell points past the shared strings") from None
    return value.text


def _column(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        raise PsixFormatError(f"PSIX workbook cell without a reference: {ref!r}")
    number = 0
    for char in letters.group(0):
        number = number * 26 + ord(char) - 64
    return number - 1


def _read(book: zipfile.ZipFile, name: str) -> bytes:
    """One workbook part, refused before reading when its declared size is over MAX_MEMBER."""
    if book.getinfo(name).file_size > MAX_MEMBER:
        raise PsixFormatError(f"PSIX workbook part {name} is larger than {MAX_MEMBER} bytes")
    return book.read(name)


def _sheet_rows(data: bytes, sheet: str) -> list[list[str]]:
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
        workbook = ET.fromstring(_read(book, "xl/workbook.xml"))
        rels = ET.fromstring(_read(book, "xl/_rels/workbook.xml.rels"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise PsixFormatError(f"PSIX export is not an XLSX workbook: {error}") from None
    rel = next((s.get(REL) for s in workbook.iter(NS + "sheet") if s.get("name") == sheet), None)
    target = next((r.get("Target") for r in rels.iter(PKG_REL + "Relationship") if r.get("Id") == rel), None)
    if not target:
        raise PsixFormatError(f"PSIX workbook has no {sheet} sheet")
    path = target.lstrip("/") if target.startswith("/") else "xl/" + target
    shared: list[str] = []
    if "xl/sharedStrings.xml" in book.namelist():
        root = ET.fromstring(_read(book, "xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(NS + "t")) for si in root.iter(NS + "si")]
    rows = []
    try:
        sheet_xml = _read(book, path)
    except KeyError:
        raise PsixFormatError(f"PSIX workbook lacks {path}") from None
    for row in ET.fromstring(sheet_xml).iter(NS + "row"):
        cells: dict[int, str] = {}
        for cell in row.iter(NS + "c"):
            cells[_column(cell.get("r", ""))] = _cell_text(cell, shared)
        rows.append([cells.get(i, "") for i in range(max(cells, default=-1) + 1)])
    return rows


def parse_inspections(data: bytes) -> list[dict[str, str]]:
    """Rows of the export's inspections sheet as {column key: text}."""
    rows = _sheet_rows(data, SHEET)
    if not rows:
        raise PsixFormatError(f"PSIX {SHEET} sheet is empty")
    header = [h.strip() for h in rows[0]]
    missing = [label for label in COLUMNS.values() if label not in header]
    if missing:
        raise PsixFormatError(f"PSIX {SHEET} sheet lacks columns: {', '.join(missing)}")
    index = {key: header.index(label) for key, label in COLUMNS.items()}
    out = []
    for row in rows[1:]:
        if any(cell.strip() for cell in row):
            out.append({key: (row[i] if i < len(row) else "").strip() for key, i in index.items()})
    return out


def _excel_date(text: str) -> str | None:
    try:
        serial = float(text)
    except ValueError:
        match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", text)
        return f"{match.group(3)}-{int(match.group(1)):02d}-{int(match.group(2)):02d}" if match else None
    return (date(1899, 12, 30) + timedelta(days=int(serial))).isoformat() if 1 < serial < 100000 else None


def _gross_tons(text: str) -> int | None:
    match = re.search(r"(\d[\d,]*)\s*-[^\n]*Gross Ton", text)
    return int(match.group(1).replace(",", "")) if match else None


@dataclass
class Vessel:
    vessel_id: str
    rows: list[dict[str, str]]

    @property
    def latest(self) -> dict[str, str]:
        return max(self.rows, key=lambda r: (_excel_date(r["started"]) or "", r["name"]))


def vessels(rows: Iterable[dict[str, str]], service: str) -> list[Vessel]:
    """Inspections of ``service`` folded per MISLE vessel id, U.S.-flagged vessels only (by latest flag)."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if _norm(row["vessel_type"]) != _norm(service):
            continue
        key = row["vessel_id"] or (row["official"] and f"on-{row['official']}")
        if key:
            grouped.setdefault(key, []).append(row)
    found = [Vessel(key, group) for key, group in sorted(grouped.items())]
    return [v for v in found if _norm(v.latest["flag"]) == _norm(US_FLAG) and v.latest["name"]]


def candidates(found: Iterable[Vessel], *, source_id: str, rights: str, retrieved_at: str,
               fallback_url: str) -> Iterator[Candidate]:
    for vessel in found:
        latest = vessel.latest
        url = vessel_url(vessel.vessel_id) if vessel.vessel_id.isdigit() else fallback_url

        def fact(field_: str, value, confidence: float) -> Fact:
            return Fact(field=field_, value=value, source_id=source_id, source_url=url, method="registry",
                        confidence=confidence, rights=rights, retrieved_at=retrieved_at)

        name = re.sub(r"\s+", " ", latest["name"]).strip()
        keys: dict[str, str] = {}
        facts = [fact("name", name, 0.8)]
        official = re.sub(r"\D", "", latest["official"])
        if 5 <= len(official) <= 8:
            keys["uscg_doc"] = official
            facts.append(fact("uscg_doc", official, 0.95))
        call_sign = latest["call_sign"].upper().replace(" ", "")
        if re.fullmatch(r"[A-Z0-9]{3,10}", call_sign):
            keys["call_sign"] = call_sign
            facts.append(fact("call_sign", call_sign, 0.85))
        if re.fullmatch(r"\d{7}", latest["imo"]):
            facts.append(fact("imo", latest["imo"], 0.95))
        if re.fullmatch(r"\d{4}", latest["built"]) and 1850 <= int(latest["built"]) <= 2100:
            facts.append(fact("year_built", int(latest["built"]), 0.9))
        tons = _gross_tons(latest["tonnage"])
        if tons is not None:
            facts.append(fact("gross_tons", tons, 0.9))
        facts.append(fact("uscg_service", {"class": latest["vessel_class"], "type": latest["vessel_type"]}, 0.95))
        sectors = sorted({r["unit"] for r in vessel.rows if r["unit"]})
        if sectors:
            facts.append(fact("uscg_sectors", sectors, 0.9))
        inspected = max((d for d in (_excel_date(r["started"]) for r in vessel.rows) if d), default=None)
        if inspected:
            facts.append(fact("uscg_last_inspection", inspected, 0.95))
        yield Candidate(source_id=source_id, name=name, keys=keys, facts=tuple(facts))


class UscgPsix:
    """The ``uscg-psix`` adapter: discover only."""

    id = ID
    kind = "discover"

    def __init__(self) -> None:
        self.stats: dict = {}

    def _form(self, response) -> Form:
        return parse_form((response.body or b"").decode("utf-8", "replace"))

    def export(self, ctx: RunContext, url: str, sector: str, service: str, since: date, until: date) -> bytes:
        """The XLSX export for one sector: GET the form, POST the search, POST the export."""
        headers = {"Content-Type": FORM_TYPE, "Referer": url}
        form = self._form(ctx.net.get(url))
        page = ctx.net.post(url, urlencode(search_fields(form, sector, service, since, until)).encode(),
                            headers=headers)
        result = self._form(page)
        workbook = ctx.net.post(url, urlencode(export_fields(result)).encode(), headers=headers,
                                max_bytes=MAX_BYTES, timeout=300)
        body = workbook.body or b""
        if not body.startswith(b"PK"):
            raise PsixFormatError("PSIX export did not return an XLSX workbook")
        return body

    def discover(self, binding, ctx: RunContext) -> Iterable[Candidate]:
        from ..net import Skipped  # fleet.net imports config, which imports this package

        params = binding.params
        url = str(params.get("url") or DEFAULT_URL)
        service = SERVICES.get(str(params.get("service") or "passenger"), str(params.get("service")))
        retrieved_at = ctx.clock()
        until = date.fromisoformat(retrieved_at[:10])
        since = until - timedelta(days=round(365.25 * float(params.get("lookback_years") or 3)))
        rows: list[dict[str, str]] = []
        self.stats = {"sectors": {}, "skips": []}
        for sector in params.get("sectors") or ():
            try:
                found = parse_inspections(self.export(ctx, url, sector, service, since, until))
            except Skipped as skip:
                self.stats["skips"].append(skip.as_dict())
                continue
            self.stats["sectors"][sector] = len(found)
            rows.extend(found)
        found_vessels = vessels(rows, service)
        self.stats["vessels"] = len(found_vessels)
        return list(candidates(found_vessels, source_id=binding.id, rights=binding.rights,
                               retrieved_at=retrieved_at, fallback_url=url))

    def enrich(self, vessel, binding, ctx: RunContext) -> Iterable[Fact]:
        return ()
