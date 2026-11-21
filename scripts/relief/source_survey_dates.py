#!/usr/bin/env python3
"""Compare saved contour credits with a Sources catalogue, without publishing anything.

Run with two local files (the contour GeoJSON and catalog/sources.json). Only
provenance.sources supplies release dates. Catalogue date text and catalogue
years are separate evidence; date-text disagreements are for human review,
not proof that survey periods are disjoint. Output is JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skippercast.platform.contracts import ID, indexed
from skippercast.platform.depth_contours import UNSTATED_SURVEY_DATE, selected_survey_date
from skippercast.relief.package import decode_document


def reconcile(contours: Path, catalogue: Path) -> dict:
    """Report one row per credited source ID, sorted by ID.

    Status describes the saved release, even when the catalogue has no match.
    A null catalogue means no matching ID; an empty object means a matched row
    with neither survey field. Neither is evidence of an unstated release date.
    """
    collection = decode_document(contours.read_bytes())
    provenance = collection.get('provenance')
    if collection.get('type') != 'FeatureCollection' or not isinstance(provenance, dict):
        raise ValueError('expected a contour FeatureCollection with provenance')
    region_id = provenance.get('region_id')
    entries = provenance.get('sources')
    if not isinstance(region_id, str) or not ID.fullmatch(region_id) or not isinstance(entries, list):
        raise ValueError('expected a contour provenance region_id and sources list')

    credited = {}
    for entry in entries:
        ident = entry.get('source_id') if isinstance(entry, dict) else None
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in credited:
            raise ValueError(f'invalid or duplicate contour source_id: {ident!r}')
        credited[ident] = entry

    sources = indexed(decode_document(catalogue.read_bytes()), 'sources')
    rows = []
    for ident, entry in sorted(credited.items()):
        # Keep absent keys distinct from explicit null and the producer's 'unstated' token.
        release = {'survey_date': entry['survey_date']} if 'survey_date' in entry else {}
        value = release.get('survey_date')
        status = 'metadata_missing'
        review = []
        if value == UNSTATED_SURVEY_DATE:
            status = 'explicitly_unstated'
        elif value is not None:
            try:
                selected_survey_date(release)  # validate only the saved date; no survey_year fallback
            except ValueError:
                review.append('invalid_release_survey_date')
            else:
                status = 'release_date_supplied'

        source = sources.get(ident)
        evidence = None
        if source is None:
            review.append('catalogue_source_missing')
        else:
            evidence = {key: source[key] for key in ('survey_date', 'survey_year') if key in source}
            catalogue_date = evidence.get('survey_date')
            if (status != 'metadata_missing' and isinstance(catalogue_date, str)
                    and catalogue_date.strip() and catalogue_date != value):
                review.append('survey_date_differs')
        rows.append({'source_id': ident, 'status': status, 'release': release,
                     'catalogue': evidence, 'review': review})
    return {'region_id': region_id, 'sources': rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('contours', type=Path, help='saved contour GeoJSON')
    parser.add_argument('catalogue', type=Path, help='Sources catalogue (catalog/sources.json)')
    args = parser.parse_args(argv)
    try:
        report = reconcile(args.contours, args.catalogue)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0  # review findings are report data, not an input/usage error


if __name__ == '__main__':
    raise SystemExit(main())
