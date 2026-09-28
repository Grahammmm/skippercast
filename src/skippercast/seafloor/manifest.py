"""Validate reviewed inventory, without promoting candidates on metadata alone."""
from pathlib import Path

from skippercast.platform.contracts import REPO, read_json


def load_manifest(root=REPO):
    from jsonschema import Draft202012Validator

    root = Path(root)
    document = read_json(root / 'catalog/surveys.json')
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
        if row['id'] in row['derived_from'] or not set(row['derived_from']) <= set(ids):
            raise ValueError('Invalid survey lineage')
        url = row['url'].lower()
        if 'bluetopo' in url or '/modeling/' in url:
            raise ValueError('Reference compilations cannot enter the survey manifest')
    return document
