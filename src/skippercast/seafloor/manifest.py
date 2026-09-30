"""Validate reviewed inventory, without promoting candidates on metadata alone."""
from pathlib import Path
from copy import deepcopy

from skippercast.platform.contracts import REPO, read_json, atomic_json


def load_manifest(root=REPO):
    return validate_manifest(read_json(Path(root)/'catalog/surveys.json'), root)


def validate_manifest(document, root=REPO):
    from jsonschema import Draft202012Validator
    root = Path(root)
    schema = read_json(root / 'catalog/survey.schema.json')
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    rows = document['surveys']
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate survey ID')
    products = [(r['url'], r['archive_member'], r['kind']) for r in rows]
    if len(products) != len(set(products)):
        raise ValueError('Duplicate survey product')
    for row in rows:
        validator.validate(row)
        profile = row.get('resolution_profile')
        if profile and (row['format'] != 'usgs-geotiff' or row['resolution_m'] == 'unknown'
                        or profile['coarse_resolution_m'] <= row['resolution_m']):
            raise ValueError('Mixed-resolution profile requires a finer USGS GeoTIFF display grid')
        if row['status'] == 'usable':
            from .rights import source_rights
            source_rights(row)
        if row['status'] in {'usable', 'physical-only'}:
            from skippercast.platform.contracts import bbox
            receipt = row['adapter_review']
            bbox(receipt['requested_bounds_wgs84'])
            if (receipt['source_sha256'] != row['sha256']
                    or receipt['vertical_datum'] != row['vertical_datum']
                    or max(receipt['native_resolution_m']) != row['resolution_m']
                    or receipt['nominal_0_300ft_pixels_in_requested_bounds'] > receipt['valid_pixels_in_requested_bounds']):
                raise ValueError('Usable source conflicts with its native adapter receipt')
        if row['id'] in row['derived_from'] or not set(row['derived_from']) <= set(ids):
            raise ValueError('Invalid survey lineage')
        url = row['url'].lower()
        if 'bluetopo' in url or '/modeling/' in url:
            raise ValueError('Reference compilations cannot enter the survey manifest')
    return document


def physical_source(row, *, physical_only=False):
    """Private-reviewed sources cannot enter the default/public processing path."""
    return row['kind'] == 'bathymetry' and (row['status'] == 'usable' or
        physical_only and row['status'] == 'physical-only')


def qualify_row(row, receipt, *, rights_url, physical_only=False):
    """Promote only after explicit rights review and a successful native adapter run."""
    from skippercast.platform.contracts import public_url
    public_url(rights_url)
    if not physical_only:
        from .rights import source_rights
        source_rights(row)
        if row['license'] != 'public-domain-us-gov' and rights_url != row['rights_review']['policy_url']:
            raise ValueError('Producer policy URL conflicts with rights review')
    if (receipt['source_id'] != row['id'] or receipt['source_sha256'] != row['sha256']
            or receipt['adapter_version'] != 'original-native-adapters-v1'
            or not 0 < receipt['nominal_0_300ft_pixels_in_requested_bounds']
                   <= receipt['valid_pixels_in_requested_bounds']):
        raise ValueError('A matching native adapter receipt with shallow-water pixels is required')
    result = deepcopy(row)
    result.update(status='physical-only' if physical_only else 'usable', hold_reason='unknown', bytes=receipt['source_bytes'],
                  horizontal_crs=receipt['horizontal_crs'], vertical_datum=receipt['vertical_datum'],
                  resolution_m=max(receipt['native_resolution_m']))
    result['adapter_review'] = {key: receipt[key] for key in (
        'adapter_version', 'source_sha256', 'cog_sha256', 'requested_bounds_wgs84',
        'valid_pixels_in_requested_bounds', 'nominal_0_300ft_pixels_in_requested_bounds',
        'native_resolution_m', 'vertical_datum', 'uncertainty_type', 'interpolation_mask')}
    result['adapter_review']['rights_source_url'] = rights_url
    if 'raster_identity' in receipt:
        result['adapter_review']['raster_identity'] = receipt['raster_identity']
    result['notes'] = ('Opened through original-native-adapters-v1; native-resolution COG cached by source hash. '
                       'Usable original producer-gridded depth in the reviewed window; no habitat or legal clearance. '
                       'Interpolation mask and acquisition independence unresolved; do not count as independent corroboration.')
    if physical_only:
        result['notes'] += ' Private physical processing only; rights are not granted and publication/export remain prohibited.'
    return result


def promote_draft(path, *, rights_url, root=REPO, physical_only=False):
    """Explicit reviewed promotion, never called by the scheduled discovery job.

    The operator reviews metadata and sets the draft row's license/date/datum
    before invoking this command. Native bytes and normalized output must still
    match; a draft or a URL alone cannot approve a source.
    """
    from .ingest import ingest
    root = Path(root)
    draft = read_json(Path(path))
    row, previous = draft['row'], draft['adapter_review']
    current, _, _ = ingest(row, previous['requested_bounds_wgs84'], root=root)
    if current['source_sha256'] != previous['source_sha256'] or current['cog_sha256'] != previous['cog_sha256']:
        raise ValueError('Native draft changed; inspect and review it again')
    qualified = qualify_row(row, current, rights_url=rights_url, physical_only=physical_only)
    document = read_json(root/'catalog/surveys.json')
    replaced = [r for r in document['surveys'] if r['id'] != row['id']]
    document['surveys'] = replaced + [qualified]
    validate_manifest(document, root)
    atomic_json(root/'catalog/surveys.json', document, indent=2)
    return qualified['id']
