"""Federal labels must agree with original producer and collection provenance."""
import pytest
from skippercast.seafloor.rights import source_rights, CSUMB_ARCHIVES, CSUMB_EXACT_ARCHIVES
from skippercast.seafloor.source_scope import government_row


def federal(**changes):
    return dict({'id': 'synthetic', 'license': 'public-domain-us-gov', 'publisher': 'USGS',
                 'url': 'https://pubs.usgs.gov/synthetic/original.zip', 'derived_from': []}, **changes)


@pytest.mark.parametrize('publisher,url', [
    ('USGS', 'https://cmgds.marine.usgs.gov/data/synthetic.zip'),
    ('USGS', 'https://pubs.usgs.gov/synthetic/original.zip'),
    ('NOAA NCEI', 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11952/BAG/synthetic.bag'),
    ('NOAA NOS Office of Coast Survey; acquired by Fugro Pelagos under NOAA contract',
     'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/synthetic.bag')])
def test_original_federal_producer_collection_remains_eligible(publisher, url):
    row = federal(publisher=publisher, url=url)
    assert source_rights(row, use='for-profit')['source_url'] == url
    assert government_row(row, {row['id']: row})


@pytest.mark.parametrize('change', [
    {'publisher': 'CSUMB (NOAA NCEI distributor)'}, {'publisher': 'CSU Monterey Bay'},
    {'publisher': 'California State University Monterey Bay'}, {'publisher': 'Seafloor Mapping Lab'},
    {'publisher': 'unknown'}, {'publisher': None}, {'url': None},
    {'url': 'http://pubs.usgs.gov/synthetic.zip'},
    {'url': 'https://pubs.usgs.gov.evil.test/synthetic.zip'},
    {'url': 'https://pubs.usgs.gov@evil.test/synthetic.zip'},
    {'url': 'https://pubs.usgs.gov/synthetic.zip?redirect=csumb'},
    {'url': 'https://pubs.usgs.gov/synthetic.zip#original'},
    {'url': 'https://pubs.usgs.gov:8443/synthetic.zip'},
    {'url': 'https://pubs.usgs.gov/synthetic/../other.zip'},
    {'url': 'https://pubs.usgs.gov/synthetic/%2e%2e/other.zip'},
    {'url': 'https://cmgds.marine.usgs.gov/data/BathymetryB_CSUMB_synthetic.zip'},
    {'publisher': 'NOAA NCEI', 'url': 'https://data.ngdc.noaa.gov/platforms/ocean/ships/unknown/data.zip'},
] + [{'publisher': 'NOAA NCEI', 'url': url} for url in sorted(CSUMB_EXACT_ARCHIVES)]
  + [{'publisher': 'NOAA NCEI', 'url': prefix+'synthetic.zip'} for prefix in CSUMB_ARCHIVES])
@pytest.mark.parametrize('use', ['for-profit', 'noncommercial'])
def test_labels_or_distributor_hosting_do_not_clear_conflicting_provenance(change, use):
    row = federal(**change)
    with pytest.raises(ValueError, match='original government publisher and URL'):
        source_rights(row, use=use)
    assert not government_row(row, {row['id']: row})


def test_derived_federal_label_cannot_launder_csumb_parent():
    parent = federal(id='parent', publisher='CSUMB (NOAA NCEI distributor)')
    child = federal(id='child', derived_from=['parent'])
    assert not government_row(child, {'parent': parent, 'child': child})
