"""SCA1123-2323-10: mpa_loader refuses every malformed statewide MPA feature with its own named error.

Contract: a feature that is not an object, whose geometry or properties is not an object, whose geometry
type is not Polygon/MultiPolygon, or whose NAME is not a string raises ValueError('Invalid MPA feature').
The daily collector catches only ValueError/OSError, so a bare AttributeError would end the always-on
protected-area source in a traceback. Stub client only; no network.
"""
import pytest

from skippercast.pipeline import coastal_watch

POLY = {'type': 'Polygon', 'coordinates': [[[-120.0, 35.0], [-120.1, 35.0], [-120.1, 35.1], [-120.0, 35.0]]]}
MULTI = {'type': 'MultiPolygon', 'coordinates': [POLY['coordinates']]}
COUNT = 150


def feature(geometry=POLY, properties=None):
    return {'type': 'Feature', 'geometry': geometry,
            'properties': {'NAME': 'Reserve'} if properties is None else properties}


class StubClient:
    def __init__(self, features):
        self.features = features

    def get(self, url, as_json=False, **_):
        if 'returnCountOnly' in url:
            return {'count': COUNT}
        return {'type': 'FeatureCollection', 'features': self.features}


def good():
    return [feature() for _ in range(COUNT)]


def test_valid_features_return_unchanged_shape():
    # Control: a fix that over-refuses (e.g. rejects MultiPolygon) or changes the returned keys fails here.
    features = good()[:-1] + [feature(MULTI)]
    out = coastal_watch.mpa_loader(StubClient(features))
    assert set(out) == {'geojson', 'feature_count', 'source_url'}
    assert out['feature_count'] == COUNT
    assert out['geojson']['features'] == features


BAD = {
    # Existing refusal must not regress.
    'point geometry': feature({'type': 'Point', 'coordinates': [0, 0]}),
    # Bug: f.get('geometry', {}) returns None for a null geometry -> AttributeError.
    'null geometry': feature(None),
    # Bug: a geometry that is a list/string has no .get -> AttributeError.
    'list geometry': feature([POLY]),
    # Bug: null properties -> AttributeError on .get('NAME').
    'null properties': {'type': 'Feature', 'geometry': POLY, 'properties': None},
    'list properties': {'type': 'Feature', 'geometry': POLY, 'properties': ['NAME']},
    # Bug: a feature that is not an object -> AttributeError on f.get.
    'string feature': 'oops',
    'null feature': None,
    # Bug: a missing geometry key must still be refused, not skipped.
    'missing geometry': {'type': 'Feature', 'properties': {'NAME': 'Reserve'}},
    'missing properties': {'type': 'Feature', 'geometry': POLY},
    # Bug: a non-string NAME slips through if the NAME check is dropped while adding the object checks.
    'non-string name': feature(properties={'NAME': 7}),
    'null name': feature(properties={'NAME': None}),
}


@pytest.mark.parametrize('bad', list(BAD.values()), ids=list(BAD))
def test_malformed_feature_raises_named_refusal(bad):
    with pytest.raises(ValueError, match='^Invalid MPA feature$'):
        coastal_watch.mpa_loader(StubClient(good()[:-1] + [bad]))


def test_count_and_transfer_guards_unchanged():
    # Guard control: the existing inventory checks keep their own messages and are not folded into the feature refusal.
    with pytest.raises(ValueError, match='Incomplete statewide MPA boundaries'):
        coastal_watch.mpa_loader(StubClient(good()[:-1]))
