#!/usr/bin/env python3
"""Report recorded support lineage from one explicitly supplied sidecar fixture.

A recorded pin is not verified against source bytes. A BAG original hash
identifies the container, not the presence or contents of embedded metadata.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

_BAG_ADAPTER = 'bag-georef-metadata-bathy-coverage/1'
_SHA256 = re.compile(r'[0-9a-f]{64}')


def _hash(value, field):
    if value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
        raise ValueError(f'{field} must be a SHA-256 hex digest or null')
    return value


def read_lineage(sidecar: Path) -> dict:
    """Read only the sidecar; never open a raster, RAT, or adapter implementation."""
    record = json.loads(sidecar.read_text(encoding='utf-8'))
    if not isinstance(record, dict) or record.get('schema') != 'sc-relief-normalized/1':
        raise ValueError('expected a sc-relief-normalized/1 sidecar')
    params = record.get('params', {})
    if not isinstance(params, dict):
        raise ValueError('params must be an object')

    original = _hash(record.get('original_sha256'), 'original_sha256')
    adapter = params.get('adapter')
    if adapter is not None:
        if not isinstance(adapter, dict) or not isinstance(adapter.get('id'), str) or not adapter['id']:
            raise ValueError('params.adapter must be null or an object with an id')
        adapter = {'id': adapter['id'], 'digest': _hash(adapter.get('digest'), 'params.adapter.digest')}

    dependencies = params.get('dependencies', [])
    if not isinstance(dependencies, list) or not all(isinstance(dep, dict) for dep in dependencies):
        raise ValueError('params.dependencies must be a list of objects')
    evidence = [
        {'role': 'support-evidence', 'sha256': _hash(dep.get('sha256'), 'support-evidence sha256')}
        for dep in dependencies if dep.get('role') == 'support-evidence'
    ]
    status = 'missing_or_unrecorded'
    if 'adapter' in params and adapter is None:
        status = 'no_adapter'
    elif adapter is not None and any(pin['sha256'] is not None for pin in evidence):
        status = 'external_pin_recorded'

    projected: dict[str, object] = {'dependencies': evidence}
    if 'adapter' in params:
        projected['adapter'] = adapter
    return {
        'original_sha256': original,
        'original_sha256_role': 'bag_container' if adapter and adapter['id'] == _BAG_ADAPTER else 'source',
        'params': projected,
        'evidence_status': status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sidecar', type=Path, help='explicit saved normalization sidecar JSON fixture')
    args = parser.parse_args()
    try:
        lineage = read_lineage(args.sidecar)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(lineage, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
