"""Hash-verified local originals from a geofetch catalog; a copy source, never a new trust source.

A local source root is a directory of already downloaded originals plus a
geofetch ``catalog.jsonl`` (one JSON row per file: ``id``, ``url``, ``sha256``,
``size`` and ``dest`` relative to the root). It only replaces the network
transfer. Every file still goes through :func:`fetch.fetch_source`, so the
reviewed URL allowlist, container rules, byte cap and the repo's pinned
checksum apply unchanged. In addition the selected local file must hash to the
catalog's checksum on every import (a warm cache does not skip this), and a
catalog checksum or size that conflicts with the repo's pin refuses the file
before any copy. A refusal never removes an already verified cache entry.
"""
import json
from pathlib import Path
import re

from .io import sha256

CATALOG = '_geofetch/catalog.jsonl'
SHA256 = re.compile(r'[a-f0-9]{64}')
IMPORTABLE = frozenset(('usable', 'physical-only'))


class LocalSourceRoot:
    def __init__(self, root, catalog=None):
        try:
            self.root = Path(root).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError(f'Local source root missing: {root}') from error
        if not self.root.is_dir():
            raise ValueError(f'Local source root is not a directory: {root}')
        self.catalog = Path(catalog) if catalog else self.root / CATALOG
        self.by_url = {}
        try:
            lines = self.catalog.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(f'Local source catalog unreadable: {self.catalog}') from error
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as error:
                raise ValueError(f'Invalid local catalog row {number}') from error
            if not (isinstance(row, dict) and isinstance(row.get('id'), str) and row['id']
                    and isinstance(row.get('url'), str) and row['url'].startswith('https://')
                    and isinstance(row.get('sha256'), str) and SHA256.fullmatch(row['sha256'])
                    and type(row.get('size')) is int and row['size'] > 0
                    and isinstance(row.get('dest'), str) and row['dest']
                    and not Path(row['dest']).is_absolute() and '..' not in Path(row['dest']).parts):
                raise ValueError(f'Invalid local catalog row {number}')
            self.by_url.setdefault(row['url'], []).append(row)

    def entry(self, url):
        """The single catalog row for ``url``, or None; conflicting duplicates refuse."""
        rows = self.by_url.get(url)
        if not rows:
            return None
        if len({(r['sha256'], r['size']) for r in rows}) != 1:
            raise ValueError('Local catalog lists conflicting checksums for one URL')
        return rows[0]

    def resolve(self, url, pinned_sha256='unknown', pinned_bytes='unknown'):
        """Return (path, catalog row) for a catalogued URL, or None if it is not catalogued."""
        row = self.entry(url)
        if row is None:
            return None
        if pinned_sha256 != 'unknown' and row['sha256'] != pinned_sha256:
            raise ValueError('Local catalog checksum conflicts with the pinned source checksum')
        if pinned_bytes != 'unknown' and row['size'] != pinned_bytes:
            raise ValueError('Local catalog byte count conflicts with the pinned source')
        path = self.root / row['dest']
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError(f'Local original missing: {row["dest"]}') from error
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError(f'Local original escapes its source root: {row["dest"]}')
        if resolved.stat().st_size != row['size']:
            raise ValueError('Local original byte count differs from its catalog row')
        # Hash the selected file itself, even when the cache already holds these
        # bytes, so a report of "imported" always means the local copy was verified.
        if sha256(resolved) != row['sha256']:
            raise ValueError('Local original checksum mismatch against its catalog row')
        return resolved, row


def import_local(row, cache, local_root, *, max_bytes=2_000_000_000):
    """Copy one catalogued original into the content-addressed cache.

    Returns (catalog row, cached path) or None when the URL is not catalogued.
    The expected checksum is the repo pin when one exists, otherwise the catalog
    checksum, so the copied bytes must match both.
    """
    from .fetch import fetch_source
    found = local_root.resolve(row['url'], row['sha256'], row['bytes'])
    if found is None:
        return None
    path, entry = found
    expected = dict(row, sha256=entry['sha256'], bytes=entry['size'])
    cached, _ = fetch_source(expected, cache, local=path, max_bytes=max_bytes)
    return entry, cached


def import_manifest(surveys, cache, local_root, *, ids=None):
    """Import reviewed manifest sources found in the local catalog; report each mapping.

    Only ``usable`` and ``physical-only`` rows (or explicitly selected ``ids``)
    are considered. Any refusal is reported per source and nothing is cached
    for it; the caller fails when ``refused`` is non-empty.
    """
    selected = [r for r in surveys if (r['id'] in ids if ids else r.get('status') in IMPORTABLE)]
    if ids and {r['id'] for r in selected} != set(ids):
        raise ValueError('Unknown survey ID: ' + ', '.join(sorted(set(ids) - {r['id'] for r in selected})))
    report = {'imported': [], 'not_catalogued': [], 'refused': []}
    for row in selected:
        try:
            result = import_local(row, cache, local_root)
        except (ValueError, FileNotFoundError) as error:
            report['refused'].append({'source_id': row['id'], 'url': row['url'], 'reason': str(error)})
            continue
        if result is None:
            report['not_catalogued'].append(row['id'])
            continue
        entry, cached = result
        report['imported'].append({'source_id': row['id'], 'catalog_id': entry['id'],
                                   'sha256': entry['sha256'], 'bytes': entry['size'], 'cache': str(cached)})
    return report
