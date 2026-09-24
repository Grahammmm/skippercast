"""Publish reviewed rules and compare sources with a fixed, reviewed baseline.

A successful HTTP request is not a legal review. Changed content stays flagged
until the registry is reviewed and its approved fingerprint is updated.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import math
import re
import time
from threading import Lock
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from ..platform.contracts import public_url

REGISTRY = Path(__file__).resolve().parents[3] / "dist/data/regulations.json"
_ecfr_lock = Lock()
_ecfr_index = {}
_ecfr_last = 0.0


def content_hash(registry):
    keys = ('jurisdiction_id', 'valid_from', 'valid_through', 'timezone', 'scope',
            'common_notes', 'area_notices', 'species', 'authority_hosts', 'reviewed_regions')
    value = {key: registry.get(key) for key in keys}
    value['sources'] = {ident: {key: spec.get(key) for key in ('name', 'url', 'normalization')}
                        for ident, spec in registry['sources'].items()}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def validate_bindings(jurisdiction, registry):
    """A source ID must resolve to the exact reviewed official document."""
    hosts = jurisdiction.get('authority_hosts', [])
    if not hosts or registry.get('authority_hosts') != hosts or registry.get('jurisdiction_id') != jurisdiction['id']:
        raise ValueError('Regulation jurisdiction and approved authorities are required')
    watches = jurisdiction['watches']
    if set(watches) != set(registry['sources']):
        raise ValueError('Every regulatory watch needs a matching reviewed source')
    for ident, definition in registry['sources'].items():
        watch = watches.get(ident)
        if not watch or watch['url'] != definition['url']:
            raise ValueError(f'Regulation source has no matching collector: {ident}')
        if urlsplit(public_url(watch['url'])).hostname not in hosts:
            raise ValueError(f'Unreviewed regulatory authority: {ident}')
        if watch.get('format', 'html') not in ('html', 'pdf', 'ecfr'):
            raise ValueError(f'Unsupported regulation format: {ident}')
        normalizer = {'html': 'text-and-links-v3', 'pdf': 'pdf-bytes-v1', 'ecfr': 'ecfr-section-text-v1'}[watch.get('format', 'html')]
        if definition.get('normalization') != normalizer:
            raise ValueError(f'Regulation normalizer differs from the reviewed contract: {ident}')
        if watch.get('format') == 'ecfr' and (f"/title-{watch.get('title')}/" not in watch['url'] or
                not watch['url'].endswith('/section-' + str(watch.get('section')))):
            raise ValueError(f'eCFR API selection does not match the reviewed URL: {ident}')
    for notice in registry.get('area_notices', []):
        if not notice.get('source_ids') or not set(notice['source_ids']) <= registry['sources'].keys():
            raise ValueError('Every area notice needs watched legal sources')
    required = set(jurisdiction.get('required_source_ids', []))
    for ident, profile in registry['species'].items():
        if not required <= set(profile['source_ids']):
            raise ValueError(f'Missing shared legal dependencies for {ident}')


def watch_jobs(watches):
    """Same bounded adapters for scheduled checks and a review packet."""
    from . import parsers
    jobs = []
    for ident, spec in watches.items():
        url = spec['url']
        if spec.get('format') == 'ecfr':
            loader = lambda c, s=spec: ecfr_section(c, s)
        elif spec.get('format', 'html') == 'pdf':
            loader = lambda c, u=url: c.get(u, as_pdf=True)
        else:
            loader = lambda c, u=url, k=spec['keywords']: parsers.page_watch(c.get(u), k)
        jobs.append((ident, spec['name'], 'page-watch', url, 36, loader))
    return jobs


def validate_region_binding(jurisdiction, registry, region):
    if jurisdiction['id'] != region['jurisdiction_id'] or jurisdiction['regulations_asset'] != region['assets']['regulations']:
        raise ValueError('Regional regulation asset must match its jurisdiction')
    reviewed = next((r for r in registry.get('reviewed_regions', []) if r['id'] == region['id']), None)
    if not reviewed or reviewed['fishing_bounds'] != region['fishing_bounds'] or registry['timezone'] != region['timezone']:
        raise ValueError('This regional footprint and timezone need a regulatory review')
    required = {s for target in region['species'] for s in (['lingcod','rockfish'] if target == 'reef' else [target])}
    if not required <= registry.get('species', {}).keys():
        raise ValueError('Regional target species need matching reviewed regulation records')


def ecfr_section(client, spec):
    # The supported API is rate-limited. Share title metadata only within a run;
    # retain the original retrieval receipt and serialize section requests.
    global _ecfr_last
    with _ecfr_lock:
        delay = 3 - (time.monotonic() - _ecfr_last)
        if delay > 0:
            time.sleep(delay)
        try:
            return _ecfr_section(client, spec)
        finally:
            _ecfr_last = time.monotonic()


def _ecfr_section(client, spec):
    """Use eCFR's supported API; title freshness is not a section amendment date."""
    title, section = spec['title'], spec['section']
    if not isinstance(title, int) or not 1 <= title <= 50 or not re.fullmatch(r'\d+\.\d+[a-z]?', section):
        raise ValueError('Invalid eCFR section request')
    key = client.now.isoformat()
    if _ecfr_index.get('key') == key:
        index = deepcopy(_ecfr_index['data'])
        client.requests.extend({**r, 'shared_within_run': True} for r in _ecfr_index['receipts'])
    else:
        index = client.get('https://www.ecfr.gov/api/versioner/v1/titles.json', as_json=True)
        _ecfr_index.clear()
        _ecfr_index.update(key=key, data=deepcopy(index), receipts=deepcopy(client.requests))
    meta = next((t for t in index['titles'] if t['number'] == title), None)
    if not meta or index.get('meta', {}).get('import_in_progress'):
        raise ValueError('eCFR title unavailable or still importing')
    date = meta['latest_issue_date']
    datetime.strptime(date, '%Y-%m-%d')
    current_through = datetime.strptime(meta['up_to_date_as_of'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    if not -1 <= (client.now - current_through).total_seconds() / 86400 <= 7:
        raise ValueError('eCFR current-through date is unavailable or over seven days old')
    url = f'https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?section={section}'
    body = client.get(url)
    if '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper():
        raise ValueError('Unexpected XML declarations')
    xml = ElementTree.fromstring(body)
    matches = [e for e in xml.iter() if e.attrib.get('TYPE') == 'SECTION' and e.attrib.get('N') == section]
    if len(matches) != 1:
        raise ValueError('eCFR response did not identify the requested section')
    text = ' '.join(' '.join(matches[0].itertext()).split())
    if not all(re.search(k, text, re.I) for k in spec['keywords']):
        raise ValueError('Expected legal content absent')
    return {'content_sha256': hashlib.sha256(text.encode()).hexdigest(), 'normalization':'ecfr-section-text-v1',
            'title':title, 'section':section, 'up_to_date_as_of':meta['up_to_date_as_of'],
            'title_latest_issue_date':date, 'source_url':url, 'interpretation':'manual review required',
            'permission_to_fish':None}


def valid_window(window, timezone='America/Los_Angeles'):
    try:
        start, end = (datetime.strptime(window[key], '%Y-%m-%d').date() for key in ('start', 'end'))
        if start > end or start.isoformat() != window['start'] or end.isoformat() != window['end']:
            return False
        if 'start_at' in window:
            opening = datetime.fromisoformat(window['start_at'].replace('Z', '+00:00'))
            if opening.tzinfo is None or opening.astimezone(ZoneInfo(timezone)).date() != start:
                return False
        if 'geography' in window:
            geographic = window['geography']
            if geographic.get('kind') != 'latitude-band' or not all(
                isinstance(geographic.get(key), (int, float)) and not isinstance(geographic[key], bool)
                and math.isfinite(geographic[key]) for key in ('south', 'north')
            ) or not -90 <= geographic['south'] < geographic['north'] <= 90:
                return False
            if not isinstance(geographic.get('source_id'), str) or not geographic.get('note'):
                return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def regulatory_snapshot(sources, now, registry=None):
    data = deepcopy(registry if registry is not None else json.loads(REGISTRY.read_text()))
    species = data.get('species', {})
    if data.get("schema_version") != 1 or not species or not all(
        isinstance(p, dict) and all(isinstance(p.get(key), str) for key in ('name', 'season', 'bag', 'size'))
        and isinstance(p.get('windows'), list) and all(valid_window(w, data.get('timezone', 'America/Los_Angeles')) for w in p['windows']) and p.get('source_ids')
        and all(ident in data.get('sources', {}) for ident in p['source_ids'])
        and all(w.get('geography', {}).get('source_id') in p['source_ids'] for w in p['windows'] if 'geography' in w)
        for p in species.values()
    ):
        raise ValueError("Regulations registry is incomplete")
    checks = {}
    for ident, expected in data["sources"].items():
        source = sources.get(ident, {})
        checked = source.get("data_retrieved_at")
        try:
            age = (now - datetime.fromisoformat(checked.replace("Z", "+00:00"))).total_seconds() / 3600
        except (ValueError, AttributeError, TypeError):
            age = float("inf")
        fingerprint = (source.get("data") or {}).get("content_sha256")
        approved = expected.get("approved_content_sha256")
        if source.get("status") != "ok" or not -1 <= age <= 36:
            status = "unavailable"
        elif source.get('url') != expected.get('url'):
            status = 'identity-mismatch'
        elif not re.fullmatch(r'[a-f0-9]{64}', approved or '') or not re.fullmatch(r'[a-f0-9]{64}', fingerprint or ''):
            status = "unreviewed"
        elif expected.get('normalization') != (source.get('data') or {}).get('normalization'):
            status = 'normalization-mismatch'
        elif fingerprint != approved:
            status = "changed"
        else:
            status = "unchanged"
        checks[ident] = {"status": status, "checked_at": source.get("checked_at"),
                         "data_retrieved_at": checked, "content_sha256": fingerprint,
                         "url": source.get('url'),
                         "normalization": (source.get('data') or {}).get('normalization'),
                         "source_status": source.get("status", "missing")}
    data["checks"] = checks
    data['rules_review_status'] = 'reviewed' if data.get('approved_rules_content_sha256') == content_hash(data) else 'content-needs-review'
    data["checked_at"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    data["review_required"] = [ident for ident, check in checks.items() if check["status"] != "unchanged"]
    return data
