"""Producer-specific release terms; distributor hosting grants no new rights."""
from datetime import date
from urllib.parse import urlsplit


def government_source(row):
    """Recognize original federal provenance, not a distributor/license label.

    NCEI's ship archives include non-federal producers. Only its NOS survey
    collection qualifies here; other federal collections need explicit review.
    """
    if row.get('license') != 'public-domain-us-gov':
        return False
    publisher = row.get('publisher')
    url = row.get('url')
    if not isinstance(publisher, str) or not isinstance(url, str):
        return False
    provenance = (publisher+' '+url).casefold()
    if any(name in provenance for name in ('csumb', 'csu monterey bay', 'sfml',
            'california state university monterey bay', 'seafloor mapping lab')):
        return False
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or '%' in parsed.path or '\\' in url
                or any(part in {'.', '..'} for part in parsed.path.split('/'))):
            return False
    except ValueError:
        return False
    if publisher in {'USGS', 'U.S. Geological Survey', 'United States Geological Survey'}:
        return parsed.hostname == 'usgs.gov' or (parsed.hostname or '').endswith('.usgs.gov')
    if publisher in {'NOAA', 'NOAA NCEI', 'NOAA NOS', 'NOAA NOS Office of Coast Survey',
            'NOAA NOS Office of Coast Survey; acquired by Fugro Pelagos under NOAA contract'}:
        return (parsed.hostname == 'data.ngdc.noaa.gov'
                and parsed.path.startswith('/platforms/ocean/nos/'))
    return False

CSUMB_LICENSE = 'csumb-public-use-noncommercial'
CSUMB_POLICY = 'https://csumb.edu/undersea/sfml-data-library/'
CSUMB_CREDIT = ('Data used in this study were acquired, processed, archived, and distributed '
                'by the Seafloor Mapping Lab of California State University Monterey Bay.')
CSUMB_NOTICE = 'Public noncommercial use only; for-profit use requires express CSUMB SFML permission. Not for navigation.'
POINT_LOBOS_ARCHIVE = ('https://data.ngdc.noaa.gov/platforms/ocean/ships/macginitie/'
                     'PointLobos/multibeam/data/version2/products/PointLobos_additional_products.tar.gz')
MONASTERY_ARCHIVE = ('https://data.ngdc.noaa.gov/platforms/ocean/ships/macginitie/'
                     'MonasteryBeach/multibeam/data/version2/products/Monastery_additional_products.tar.gz')
CSUMB_EXACT_ARCHIVES = frozenset((POINT_LOBOS_ARCHIVE, MONASTERY_ARCHIVE))
CSUMB_ARCHIVES = (
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/',
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/',
)


def source_rights(row, *, use="noncommercial", today=None):
    """Return exportable terms only for a reviewed, original producer source."""
    if use not in {'noncommercial', 'for-profit'}:
        raise ValueError('Unknown deployment source-use profile')
    if row.get('license') == 'public-domain-us-gov':
        if not government_source(row):
            raise ValueError('Source public-domain rights require original government publisher and URL; producer permission unresolved')
        return {'source_id': row['id'], 'license': row['license'],
                'source_url': row['url'], 'policy_url': row.get('adapter_review', {}).get('rights_source_url', ''),
                'attribution': row.get('publisher', 'Original USGS / NOAA survey'),
                'notice': 'Original US government data; retain source attribution and survey limitations.'}
    if use != 'noncommercial':
        raise ValueError('For-profit publication requires express producer permission')
    review = row.get('rights_review', {})
    if (row.get('license') != CSUMB_LICENSE
            or review.get('policy_url') != CSUMB_POLICY
            or review.get('source_sha256') != row.get('sha256')
            or review.get('producer') != 'CSUMB SFML'
            or review.get('allowed_use') != 'noncommercial'
            or review.get('attribution') != CSUMB_CREDIT
            or review.get('navigation_use') is not False
            or review.get('for_profit_permission') != 'required-not-obtained'
            or not (row.get('url', '').startswith(CSUMB_ARCHIVES)
                    or row.get('url') in CSUMB_EXACT_ARCHIVES)
            or not ('CSUMB' in row.get('publisher', '') or 'CSU Monterey Bay' in row.get('publisher', ''))):
        raise ValueError('Source publication rights are unqualified or conflict with producer review')
    try:
        checked = date.fromisoformat(review['reviewed_on'])
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError('Source terms require an actual dated producer review') from error
    if checked > (today or date.today()):
        raise ValueError('Source terms review cannot be dated in the future')
    return {'source_id': row['id'], 'license': CSUMB_LICENSE, 'source_url': row['url'],
            'policy_url': CSUMB_POLICY, 'attribution': CSUMB_CREDIT,
            'notice': CSUMB_NOTICE, 'commercial_use': 'permission-required',
            'navigation_use': False, 'reviewed_on': checked.isoformat()}


def feature_rights(source_ids, sources, *, use="noncommercial"):
    """Every contributor must resolve, including interpreted substrate sources."""
    if not source_ids or any(ident not in sources for ident in source_ids):
        raise ValueError('Feature source attribution is incomplete')
    return [source_rights(sources[ident], use=use) for ident in sorted(set(source_ids))]


def deployment_use(root):
    """An explicit deployment profile overrides no producer restrictions."""
    import json
    import os
    from pathlib import Path
    path = Path(root)/'deployments/production.json'
    if not path.exists():
        # Missing deployment policy is never permission to release restricted data.
        return 'for-profit'
    policy = json.loads(path.read_text())
    use = policy.get('source_use')
    monetization = policy.get('monetization')
    if use not in {'noncommercial', 'for-profit'} or monetization not in {'none', 'paid'}:
        raise ValueError('Deployment requires explicit source_use and monetization')
    if monetization == 'paid' and use != 'for-profit':
        raise ValueError('Paid deployment cannot use the noncommercial source profile')
    configured = os.environ.get('SKIPPERCAST_SOURCE_USE')
    if configured is not None:
        if configured not in {'noncommercial', 'for-profit'}:
            raise ValueError('Unknown deployment source-use override')
        if use == 'for-profit' and configured == 'noncommercial':
            raise ValueError('Environment cannot weaken deployment source-use policy')
        use = configured
    return use


def check_deployment(root):
    """Fail before deployment/publication if enabled sources conflict with use."""
    import json
    from pathlib import Path
    use = deployment_use(root)
    from .source_scope import scoped_manifest
    manifest, scope = scoped_manifest(root, json.loads((Path(root)/'catalog/surveys.json').read_text()))
    rows = manifest['surveys']
    for row in rows:
        if row['status'] == 'usable':
            source_rights(row, use=use)
    return {'source_use': use, 'usable_sources': sum(r['status'] == 'usable' for r in rows),
            **({'source_scope': scope} if scope is not None else {})}


if __name__ == '__main__':
    import json
    from pathlib import Path
    print(json.dumps(check_deployment(Path(__file__).resolve().parents[3])))
