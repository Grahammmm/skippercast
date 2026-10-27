"""Read-only recipe rights coverage. Completeness is not permission to publish."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

# Direct script execution must use this checkout, never an ambient editable install.
ROOT = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from skippercast.seafloor import rights as rights_module

REGISTER = 'docs/legal/data-rights-register.md'
SLUG = re.compile(r'[a-z0-9][a-z0-9_-]*\Z')
URL = re.compile(r'(?:[A-Za-z][A-Za-z0-9+.-]*:|//)[^\s<>\"\x27]+')


def _safe_path(path, *, exists=True):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Paths must be absolute and contain no parent traversal')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink paths are not accepted')
    if exists and not path.exists():
        raise ValueError('Required input path is missing')
    return path


def _json(path):
    _safe_path(path)
    if not path.is_file():
        raise ValueError('JSON input must be a regular file')
    return json.loads(path.read_text(encoding='utf-8'))


def _sanitize(value):
    """Keep resolver semantics but project every URL to a host, even inside text."""
    if isinstance(value, str):
        def host(match):
            try:
                return urlsplit(match.group()).hostname or '[URL host unavailable]'
            except ValueError:
                return '[URL host unavailable]'
        return URL.sub(host, value).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    if isinstance(value, dict):
        return {str(_sanitize(k)): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_sanitize(v) for v in value]
    return value


def _catalog(root):
    catalog = {}
    source_path = root / 'catalog/sources.json'
    document = _json(source_path)
    if not isinstance(document, dict) or not isinstance(document.get('sources'), list):
        raise ValueError('Catalog must contain a sources array')
    def add(row, locator):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            raise ValueError('Catalog entries require string IDs')
        catalog.setdefault(row['id'], []).append((row, locator))
    for index, row in enumerate(document['sources']):
        add(row, 'catalog/sources.json#sources/' + str(index))
    candidates = root / 'catalog/candidates'
    _safe_path(candidates, exists=False)
    if candidates.exists():
        if not candidates.is_dir():
            raise ValueError('Candidate catalog must be a directory')
        for path in sorted(candidates.glob('*.json')):
            add(_json(path), path.relative_to(root).as_posix())
    return catalog


def _verdict(rows):
    return 'COMPLETE' if rows and all(row['catalog_found'] and row['rights'] is not None
                                     and row['attribution_present'] and row['error'] is None
                                     for row in rows) else 'INCOMPLETE'


def check_coverage(repo_root, recipe):
    """Join every unique recipe slug to its unmodified catalog row and resolver.

    No nested-rights translation, status change, fetching, producer inference or
    legal conclusion. Missing/ambiguous entries stay unresolved.
    """
    root = _safe_path(repo_root)
    if not root.is_dir():
        raise ValueError('Repository root must be a directory')
    recipe = _safe_path(recipe)
    document = _json(recipe)
    slugs = document.get('sources') if isinstance(document, dict) else None
    if (not isinstance(slugs, list) or not slugs
            or any(not isinstance(s, str) or not SLUG.fullmatch(s) for s in slugs)):
        raise ValueError('Recipe requires a nonempty array of source slugs')
    catalog = _catalog(root)
    rows = []
    for slug in dict.fromkeys(slugs):
        entries = catalog.get(slug, [])
        result = {'slug': slug, 'catalog_found': bool(entries),
                  'catalog_locators': [locator for _, locator in entries],
                  'rights': None, 'error': None, 'attribution_present': False}
        if not entries:
            result['error'] = {'type': 'CatalogEntryMissing', 'message': 'Source slug is absent from the catalog'}
        elif len(entries) != 1:
            result['error'] = {'type': 'CatalogEntryAmbiguous', 'message': 'Source slug has multiple catalog entries'}
        else:
            try:
                terms = rights_module.source_rights(entries[0][0])
                if not isinstance(terms, dict):
                    raise TypeError('source_rights did not return an object')
                result['rights'] = terms
                credit = terms.get('attribution')
                result['attribution_present'] = isinstance(credit, str) and bool(credit.strip())
            except Exception as error:
                result['error'] = {'type': type(error).__name__, 'message': str(error)}
        rows.append(result)
    return _sanitize({'schema_version': 1, 'verdict': _verdict(rows), 'sources': rows,
                      'lacking_rights': [r['slug'] for r in rows if r['error'] or not r['attribution_present']],
                      'human_register': REGISTER,
                      'qualification': 'Coverage only; REVIEW REQUIRED. No legal conclusion, source promotion, navigation or publication permission.'})


def render_table(report):
    lines = ['Source | Catalog entry | Resolver result | Attribution text',
             '-------|---------------|-----------------|-----------------']
    for row in report['sources']:
        reason = row['error']
        result = (reason['type'] + ': ' + reason['message']) if reason else json.dumps(row['rights'], sort_keys=True)
        lines.append(' | '.join([row['slug'], 'found' if row['catalog_found'] else 'missing', result,
                                 'present' if row['attribution_present'] else 'absent']))
    lines.extend(['Verdict: ' + report['verdict'],
                  'Slugs lacking rights: ' + (', '.join(report['lacking_rights']) or 'none'),
                  'Human register: ' + REGISTER, report['qualification']])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', required=True, type=Path)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        output = _safe_path(args.output_root, exists=False)
        if output.exists():
            raise ValueError('Output root must be new; existing output is never overwritten')
        report = check_coverage(args.repo_root, args.recipe)
        output.mkdir(parents=True, exist_ok=False)
        text = render_table(report)
        (output / 'coverage.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        (output / 'coverage.txt').write_text(text, encoding='utf-8')
        print(text, end='')
        return 0
    except (OSError, ValueError, TypeError) as error:
        print('INPUT_ERROR ' + type(error).__name__ + ': ' + _sanitize(str(error)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
