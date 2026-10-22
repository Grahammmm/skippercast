"""Render an offline, review-required rights page from actual mosaic contributors.

This is research/export tooling, not a publication or commercial-clearance gate.
See README-rights.md for the manifest contract and CLI.
"""
from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


NOT_FOR_NAVIGATION = (
    "Not for navigation or any purpose involving safety at sea. "
    "Research preview only; not an official nautical chart. "
    "Depths, contours and datum adjustments may be incomplete or inaccurate."
)
CSUMB_NOTICE = (
    "CSUMB Seafloor Mapping Lab policy permits non-profit use with acknowledgment. "
    "For-profit permission question: express written permission is required, or "
    "owner/counsel must resolve whether the named USGS release terms govern. "
    "A public-domain or CC0 release label does not resolve this question. "
    "Commercial use is not cleared by this page."
)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _url(value: object, field: str) -> str:
    value = _text(value, field)
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or any(c.isspace() for c in value)):
        raise ValueError(f"{field} must be an HTTPS URL without credentials or whitespace")
    return value


def _used_sources(manifest: object) -> list[dict]:
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int:
        raise ValueError("manifest must have integer schema_version=1")
    if manifest["schema_version"] != 1 or not isinstance(manifest.get("sources"), list):
        raise ValueError("manifest must have schema_version=1 and sources[]")
    used = []
    seen = set()
    for row in manifest["sources"]:
        if not isinstance(row, dict):
            raise ValueError("each source must be an object")
        source_id = _text(row.get("source_id"), "source_id")
        if source_id in seen:
            raise ValueError(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        cells = row.get("contributed_cells")
        if type(cells) is not int or cells < 0:
            raise ValueError(f"{source_id}: contributed_cells must be a nonnegative integer")
        if cells == 0:
            continue
        name = _text(row.get("name"), f"{source_id}.name")
        source_url = _url(row.get("source_url"), f"{source_id}.source_url")
        sha = _text(row.get("sha256"), f"{source_id}.sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"{source_id}: sha256 must be 64 lowercase hex characters")
        rights = row.get("rights")
        if not isinstance(rights, dict):
            raise ValueError(f"{source_id}: rights object is required")
        license_text = _text(rights.get("license"), f"{source_id}.rights.license")
        terms_url = _url(rights.get("terms_url"), f"{source_id}.rights.terms_url")
        attribution = _text(rights.get("attribution"), f"{source_id}.rights.attribution")
        if type(rights.get("csumb_involved")) is not bool:
            raise ValueError(f"{source_id}: rights.csumb_involved must be boolean")
        # Preserve the hold even if an obvious CSUMB source is incorrectly tagged false.
        evidence = " ".join((source_id, name, source_url, license_text, terms_url, attribution)).lower()
        csumb = rights["csumb_involved"] or "csumb" in evidence or "seafloor mapping lab" in evidence
        used.append(dict(source_id=source_id, name=name, source_url=source_url,
                         sha256=sha, contributed_cells=cells, license=license_text,
                         terms_url=terms_url, attribution=attribution, csumb=csumb))
    return sorted(used, key=lambda row: row["source_id"])


def render_manifest(manifest: object, manifest_sha256: str | None = None) -> str:
    """Return escaped standalone HTML. Never infer usage, licence or clearance.

    The exporter supplies contributed_cells from its final contributor raster.
    This renderer validates metadata, not raster coverage or legal sufficiency.
    """
    sources = _used_sources(manifest)
    assert isinstance(manifest, dict)  # validated by _used_sources
    if manifest_sha256 is None:
        manifest_sha256 = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("invalid manifest sha256")
    parts = [
        '<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>Coast data rights and attribution — review required</title></head>\n<body><main>',
        '<h1>Coast data rights and attribution</h1>',
        f'<p role="note">{NOT_FOR_NAVIGATION}</p>',
        '<p>Status: <strong>review_required</strong>. This generated inventory is not legal advice, '
        'semantic acceptance, permission to publish, or commercial-use clearance. '
        'Source terms are recorded from the manifest, not independently verified here. '
        'Use does not imply endorsement by any source, GEBCO, the IHO or the IOC. '
        'Do not misrepresent the original data or these derivatives.</p>',
        f'<p>Input manifest SHA-256: <code>{manifest_sha256}</code></p>',
        f'<p>Sources with contributed_cells &gt; 0: {len(sources)}. '
        'Counts are declarations from the final contributor raster; this page does not inspect rasters. '
        'Zero-contribution inputs are excluded.</p>',
    ]
    if manifest.get("fixture_only") is True:
        parts.append('<p><strong>SYNTHETIC FIXTURE ONLY — hashes, cell counts and source rows '
                     'are test data, not evidence of acquisition or actual coverage.</strong></p>')
    if any(row["csumb"] for row in sources):
        parts.append(f'<section><h2>Unresolved CSUMB for-profit permission</h2><p>{CSUMB_NOTICE}</p>'
                     '<p>Owner/counsel review required before commercial use; no request has been sent.</p></section>')
    if not sources:
        parts.append('<p>No sources contributed to this output according to the manifest.</p>')
    for row in sources:
        e = {key: escape(str(value), quote=True) for key, value in row.items()}
        parts.extend([
            f'<section><h2>{e["name"]}</h2>',
            f'<p>Source ID: <code>{e["source_id"]}</code>; contributed cells: {e["contributed_cells"]}</p>',
            f'<p><a href="{e["source_url"]}">Source documentation</a>; '
            f'<a href="{e["terms_url"]}">Licence / terms evidence</a></p>',
            f'<p>Input file SHA-256: <code>{e["sha256"]}</code></p>',
            f'<p>Recorded licence / terms: {e["license"]}</p>',
            f'<p>Attribution: {e["attribution"]}</p>',
            f'<p>Rights review: {"needs_permission — " + CSUMB_NOTICE if row["csumb"] else "review_required — recorded terms are not a clearance decision."}</p>',
            '</section>',
        ])
    parts.append('</main></body></html>\n')
    return '\n'.join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.manifest.resolve() == args.output.resolve():
            raise ValueError("output must not overwrite the input manifest")
        raw = args.manifest.read_bytes()
        page = render_manifest(json.loads(raw), hashlib.sha256(raw).hexdigest())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent,
                                             prefix=".coast-rights-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(page)
            os.replace(temporary, args.output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"coast_rights: {exc}\n")
    print(f"Built {args.output}: review_required; not for navigation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
