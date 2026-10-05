"""``file-import``: vessels from an owner-supplied file in ``<FLEET_VAR>/<region>/inputs/`` (design section 6).

The one format so far is ``cdfw-cpfv-v1``: the CDFW Commercial Passenger Fishing
Vessel licence list the owner requests under the California Public Records Act
(docs/plans/charter-fleet/open-questions.md, Q4 and its appendix). It is a CSV
with the fields that request asks for, matched by header name (case, spaces and
punctuation ignored; the known spellings are in ``COLUMN_SETS``):

| Column | Becomes |
| --- | --- |
| vessel name | the candidate's name (required) |
| CDFW commercial boat registration ("FG") number | fact ``cdfw.fg_number`` |
| CPFV licence number, licence year | facts ``cdfw.cpfv_licence_number``, ``cdfw.licence_year`` |
| licensee name | fact ``operator_business``, **only when the licensee is an entity** |
| USCG documentation number / CF registration | stable keys ``uscg_doc`` / ``state_reg`` |
| home port or port of operation | ``port_hint`` when it names a port of the region |
| CPFV crab trap validation | fact ``cdfw.crab_trap_validation`` (true/false) |

A licensee that is not an entity (no LLC, Inc., Corp. or similar suffix) is an
individual's name and is dropped: it never reaches a candidate, a fact or the
report (only a count). The file itself stays under ``<FLEET_VAR>`` and never
enters git.

A fact needs an https ``source_url``; a file has none, so it is the agency's
records-request page (``fleet.json`` ``agencies``, or the binding's
``source_url``) with ``#<binding id>-<sha256 of the file, 12 hex>`` appended, so
each response file is its own record and re-importing the same file re-sees
the same facts.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping

from .base import Candidate, Fact, RunContext

ID = "file-import"
CONFIDENCE = 0.9

COLUMN_SETS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "cdfw-cpfv-v1": {
        "vessel_name": ("vesselname", "vessel", "boatname", "nameofvessel"),
        "fg_number": ("fgnumber", "fg", "fgno", "cdfwregistrationnumber", "commercialboatregistrationnumber",
                      "commercialboatregistration", "boatregistrationnumber", "cdfwboatregistration"),
        "licence_number": ("cpfvlicencenumber", "cpfvlicensenumber", "licencenumber", "licensenumber", "cpfvlicence",
                           "cpfvlicense", "licenceno", "licenseno"),
        "licence_year": ("licenceyear", "licenseyear", "year"),
        "licensee_name": ("licenseename", "licenceename", "licensee", "licencee", "licenceholder", "licenseholder"),
        "uscg_doc": ("uscgdocumentationnumber", "uscgofficialnumber", "uscgdoc", "documentationnumber",
                     "officialnumber", "uscgnumber"),
        "cf_number": ("cfnumber", "cfregistration", "cfregistrationnumber", "stateregistration",
                      "californiaregistrationnumber"),
        "home_port": ("homeport", "portofoperation", "port"),
        "crab_trap_validation": ("crabtrapvalidation", "cpfvcrabtrapvalidation"),
    },
}
REQUIRED = {"cdfw-cpfv-v1": ("vessel_name",)}
ONE_OF = {"cdfw-cpfv-v1": ("fg_number", "licence_number")}

# A licensee kept as operator_business: a business entity. Trusts and estates are often an individual's, so not kept.
ENTITY = re.compile(r"\b(?:L\.?\s?L\.?\s?C|INC(?:ORPORATED)?|CORP(?:ORATION)?|CO(?:MPANY)?|LTD|LIMITED|L\.?\s?L\.?\s?P"
                    r"|L\.?\s?P|PLLC|P\.?\s?C)\b\.?\s*$", re.IGNORECASE)
IDENT = re.compile(r"[^A-Z0-9]")
TRUE = {"y", "yes", "true", "1", "x", "issued"}
FALSE = {"n", "no", "false", "0", ""}


class FileImportError(ValueError):
    """The input file does not match its column set (a missing required column, an unreadable file)."""


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (header or "").lower())


def is_entity(name: str) -> bool:
    """True for a business licensee (``Sea Example Sportfishing, LLC``); False for an individual's name."""
    return bool(ENTITY.search(" ".join((name or "").split())))


def _ident(value: str) -> str | None:
    cleaned = IDENT.sub("", (value or "").upper())
    return cleaned[:20] or None


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def input_path(binding, ctx: RunContext) -> Path:
    """``params.path`` under ``<FLEET_VAR>/<region>/`` (``inputs/...``); never outside it."""
    relative = PurePosixPath(str(binding.params.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "inputs":
        raise FileImportError(f"{binding.id}: params.path must be a relative path under inputs/")
    return ctx.run_dir.parents[1].joinpath(*relative.parts)


def read_rows(data: bytes, column_set: str) -> list[dict[str, str]]:
    """Rows as {canonical column: value}, or FileImportError when a required column is missing."""
    if column_set not in COLUMN_SETS:
        raise FileImportError(f"unknown column set {column_set!r}")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")
    reader = csv.DictReader(io.StringIO(text))
    aliases = {alias: canonical for canonical, names in COLUMN_SETS[column_set].items() for alias in names}
    mapping = {}
    for header in reader.fieldnames or []:
        canonical = aliases.get(_key(header))
        if canonical and canonical not in mapping.values():
            mapping[header] = canonical
    present = set(mapping.values())
    missing = [c for c in REQUIRED[column_set] if c not in present]
    if missing or not present & set(ONE_OF[column_set]):
        need = missing or [" or ".join(ONE_OF[column_set])]
        raise FileImportError(f"{column_set}: missing column(s) {', '.join(need)}")
    return [{canonical: (row.get(header) or "").strip() for header, canonical in mapping.items()} for row in reader]


class FileImport:
    id = ID
    kind = "discover"

    def __init__(self):
        self.report: dict[str, Any] = {}

    def enrich(self, vessel, binding, ctx: RunContext):
        return []

    def _source_url(self, binding, ctx: RunContext, digest: str) -> str:
        base = binding.params.get("source_url")
        if not base:
            licensing = [a for a in ctx.region.agencies if a.kind == "licensing" and a.records_request_url]
            if not licensing:
                raise FileImportError(f"{binding.id}: no params.source_url and no licensing agency records_request_url")
            base = licensing[0].records_request_url
        if not str(base).startswith("https://"):
            raise FileImportError(f"{binding.id}: source_url must be https")
        return f"{str(base).split('#', 1)[0]}#{binding.id}-{digest[:12]}"

    def _port(self, text: str, ctx: RunContext) -> str | None:
        wanted = _norm(text)
        if not wanted:
            return None
        for port in ctx.region.ports:
            if wanted in {_norm(port.id), *(_norm(part) for part in port.name.split("·"))}:
                return port.id
        return None

    def discover(self, binding, ctx: RunContext) -> Iterable[Candidate]:
        report = self.report.setdefault(binding.id, {"rows": 0, "candidates": 0, "individual_licensees_dropped": 0,
                                                     "rows_without_name": 0})
        path = input_path(binding, ctx)
        if not path.is_file():
            report["status"] = "skipped"
            report["reason"] = f"input file not found: {binding.params.get('path')}"
            return []
        data = path.read_bytes()
        rows = read_rows(data, str(binding.params.get("columns", "")))
        source_url = self._source_url(binding, ctx, hashlib.sha256(data).hexdigest())
        now = ctx.clock()
        out = []

        def fact(field: str, value: Any) -> Fact:
            return Fact(field, value, binding.id, source_url, "registry", CONFIDENCE, binding.rights, now)

        for row in rows:
            report["rows"] += 1
            name = " ".join(row.get("vessel_name", "").split())
            if not name:
                report["rows_without_name"] += 1
                continue
            facts = [fact("name", name)]
            if row.get("fg_number"):
                facts.append(fact("cdfw.fg_number", _ident(row["fg_number"])))
            if row.get("licence_number"):
                facts.append(fact("cdfw.cpfv_licence_number", _ident(row["licence_number"])))
            if row.get("licence_year"):
                facts.append(fact("cdfw.licence_year", row["licence_year"][:20]))
            licensee = " ".join(row.get("licensee_name", "").split())
            if licensee:
                if is_entity(licensee):
                    facts.append(fact("operator_business", licensee[:120]))
                else:
                    report["individual_licensees_dropped"] += 1   # a person's name: dropped, never stored
            crab = row.get("crab_trap_validation", "").strip().lower()
            if crab in TRUE or crab in FALSE - {""}:
                facts.append(fact("cdfw.crab_trap_validation", crab in TRUE))
            keys = {k: v for k, v in (("uscg_doc", _ident(row.get("uscg_doc", ""))),
                                      ("state_reg", _ident(row.get("cf_number", "")))) if v}
            out.append(Candidate(source_id=binding.id, name=name, port_hint=self._port(row.get("home_port", ""), ctx),
                                 keys=keys, facts=tuple(f for f in facts if f.value not in (None, ""))))
        report["status"] = "ok"
        report["candidates"] = len(out)
        return out
