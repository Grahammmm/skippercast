"""F11-16: interpreted habitat keeps the catalogued canonical ``year``."""
import pytest

pytest.importorskip('shapely')
pytest.importorskip('pyproj')

from shapely.geometry import box  # noqa: E402

from skippercast.seafloor import bedrock_habitat as bh, classified_habitat as ch  # noqa: E402

POLICY = {'id': 'fixture-v1', 'metadata_sha256': 'c' * 64}
BEDROCK_POLICY = {**POLICY, 'interpretation_method': bh.METHOD}


def _row(**extra):
    row = {'id': 'native', 'resolution_m': 2., 'vertical_datum': 'unknown'}
    row.update(extra)
    return row


BINDING = {'row': {'id': 'classes'}}


def _classified_year(row):
    return ch.features_for([box(0, 0, 50, 50)], 'fixture', POLICY, row,
                           BINDING)['features'][0]['properties']['source_year']


def _bedrock_year(row):
    patch = bh.Patch('1', 'Jo', box(0, 0, 50, 50), 2500, 'EPSG:3310')
    return bh.features_for([patch], 'fixture', BEDROCK_POLICY, row,
                           BINDING)['features'][0]['properties']['source_year']


@pytest.mark.parametrize('year_of', [_classified_year, _bedrock_year])
def test_canonical_year_is_preserved(year_of):
    assert year_of(_row(year=2014)) == 2014


@pytest.mark.parametrize('year_of', [_classified_year, _bedrock_year])
def test_missing_year_stays_unknown(year_of):
    assert year_of(_row()) == 'unknown'
    assert year_of(_row(year=None)) == 'unknown'


@pytest.mark.parametrize('year_of', [_classified_year, _bedrock_year])
def test_legacy_survey_year_still_read_when_year_absent(year_of):
    assert year_of(_row(survey_year=2009)) == 2009
    assert year_of(_row(year=2014, survey_year=2009)) == 2014
