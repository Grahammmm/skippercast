"""Producer-specific release terms; distributor hosting grants no new rights."""
from datetime import date

CSUMB_LICENSE = 'csumb-public-use-noncommercial'
CSUMB_POLICY = 'https://csumb.edu/undersea/sfml-data-library/'
CSUMB_CREDIT = ('Data used in this study were acquired, processed, archived, and distributed '
                'by the Seafloor Mapping Lab of California State University Monterey Bay.')
CSUMB_NOTICE = 'Public noncommercial use only; for-profit use requires express CSUMB SFML permission. Not for navigation.'
CSUMB_ARCHIVES = (
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/',
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/',
)


def source_rights(row, *, use="noncommercial", today=None):
    """Return exportable terms only for a reviewed, original producer source."""
    if use not in {'noncommercial', 'for-profit'}:
        raise ValueError('Unknown deployment source-use profile')
    if row.get('license') == 'public-domain-us-gov':
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
            or not row.get('url', '').startswith(CSUMB_ARCHIVES)
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
