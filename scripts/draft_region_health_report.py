"""Report one draft region's legal and source health (draft-region-health.yml).

Exit 0 when healthy, 1 when the evidence needs review, is unreadable or misshaped
(named by file and key) or no receipt exists, 2 on a usage error (incl. a --region that is not a plain region id). A failed
past-day landing report (`catches-*`) is not
counted as a source fetch failure: the 5-of-7-day coverage gate
(`critical_available`) decides whether missing reports matter.
"""
import argparse
import json
import os
import re
from pathlib import Path

PAST_DAY_REPORT = 'catches-'
# Exception type name (the part of a collector issue before the first ': ') -> class. The rest can
# hold provider page text: only the class is printed, plus the status of http.HTTPStatusError ('HTTP 503 from host').
ERROR_CLASSES = {name: cls for cls, names in (
    ('http', 'HTTPStatusError'), ('transport', 'TransportError TLSVerificationError TimeoutError ConnectionError'),
    ('contract', 'ContractError BodyTooLarge DisallowedHost'),
    ('parse', 'ValueError KeyError IndexError TypeError JSONDecodeError UnicodeDecodeError'),
) for name in names.split()}
_HTTP_STATUS = re.compile(r'(?:HTTP )?(\d{3})(?!\d)')
REGION_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')


def error_class(issue):
    """The error class of one collector issue, from its exception type name only."""
    if not isinstance(issue, str) or not issue.strip():
        return 'other'
    name, _, rest = issue.partition(': ')
    cls = ERROR_CLASSES.get(name, 'other')
    if name == 'ValueError' and rest == 'Empty response':
        return 'empty'
    if cls == 'http':
        status = _HTTP_STATUS.match(rest)
        if status:
            return f'http {status.group(1)}'
    return cls


class Unreadable(Exception):
    """An input that cannot be read or has the wrong shape; the message holds file and key only."""


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise Unreadable(f'{path.name}: unreadable JSON') from None


def _shape(evidence, rules):
    """Raise Unreadable naming the first missing or wrongly typed key, never the file content."""
    def get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else None
    health, sources, issues = get(evidence, 'health'), get(evidence, 'sources'), get(get(evidence, 'health'), 'issues')
    checks = [('health', isinstance(health, dict)),
              ('health.issues', isinstance(issues, list) and all(isinstance(i, str) for i in issues))]
    checks += [(f'health.{key}', type(get(health, key)) is int) for key in ('sources_ok', 'sources_total')]
    checks += [('health.critical_available', isinstance(get(health, 'critical_available'), bool)),
               ('sources', isinstance(sources, dict))]
    for ident, source in (sources.items() if isinstance(sources, dict) else ()):
        checks += [(f'sources.{ident}', isinstance(source, dict)),
                   (f'sources.{ident}.status', isinstance(get(source, 'status'), str))]
    checks = [('latest.json', key, ok) for key, ok in checks]
    checks.append(('regulations-health.json', 'review_required', isinstance(get(rules, 'review_required'), list)))
    for name, key, ok in checks:
        if not ok:
            raise Unreadable(f'{name}: {key} missing or wrong type')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Report draft region legal and source health.')
    parser.add_argument('--region', required=True)
    parser.add_argument('--root', default='var/draft-rehearsal')
    parser.add_argument('--summary', default=os.environ.get('GITHUB_STEP_SUMMARY'))
    args = parser.parse_args(argv)
    if not args.summary:
        parser.error('--summary or GITHUB_STEP_SUMMARY is required')
    if not REGION_ID.fullmatch(args.region):
        parser.error('--region must be a plain region id')
    region = args.region
    root = Path(args.root) / region / 'regions' / region
    if not (root / 'latest.json').is_file():
        raise SystemExit('Draft collector produced no regional receipt')
    try:
        evidence, rules = _read(root / 'latest.json'), _read(root / 'regulations-health.json')
        _shape(evidence, rules)
    except Unreadable as bad:
        with open(args.summary, 'a') as out:
            out.write(f'## {region} draft rehearsal\nDraft evidence unreadable: {bad}\n')
        raise SystemExit(f'Draft evidence unreadable: {bad}') from None
    health = evidence['health']
    unknown = [ident for ident in health['issues'] if ident not in evidence['sources']]
    if unknown:
        raise SystemExit(f"Draft evidence names unknown sources: {', '.join(unknown)}")
    fetch_failed = [ident for ident in health['issues']
                    if evidence['sources'][ident]['status'] in ('failed', 'retained')]
    past_day = [ident for ident in fetch_failed if ident.startswith(PAST_DAY_REPORT)]
    source_failures = [ident for ident in fetch_failed if ident not in past_day]
    classes = {ident: error_class(evidence['sources'][ident].get('issue')) for ident in fetch_failed}
    for ident in fetch_failed:
        print(f"{region} {ident}: {classes[ident]}")
    with open(args.summary, 'a') as out:
        out.write(f"## {region} draft rehearsal\n")
        out.write(f"{health['sources_ok']}/{health['sources_total']} sources healthy; legal source changes or failures: {len(rules['review_required'])}; source fetch failures: {len(source_failures)}.\n")
        if past_day:
            out.write(f'Past-day landing reports that failed: {len(past_day)} (left to the 5-of-7 coverage gate).\n')
        out.write('This is unpublished source evidence, not fishing permission or site clearance.\n')
        for issue in health['issues']:
            out.write(f'- {issue}: {classes[issue]}\n' if issue in classes else f'- {issue}\n')
    if rules['review_required'] or source_failures or not health['critical_available']:
        raise SystemExit('Draft evidence needs review before regional promotion')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
