"""A regional build uses one validated catalog pair, not one pair per consumer."""
import json
from collections import Counter
from pathlib import Path

import pytest

from skippercast.platform import build, contracts


SOURCE = 'fixture-source'
NEEDS = ('surface-currents', 'wind-ensemble', 'wave-ensemble', 'wave-observations')
URL = 'https://example.org/fixture'


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def synthetic_build(tmp_path, monkeypatch):
    source = dict(id=SOURCE, documentation_url=URL, needs=NEEDS, review_status='approved',
                  rights=dict(license='public-domain', commercial_use='allowed', attribution_required=False))
    write(tmp_path, 'catalog/sources.json', dict(schema_version=1, sources=[source]))
    write(tmp_path, 'catalog/data-needs.json', dict(schema_version=1, needs=[
        dict(id=need, name=need, gates=['fixture-gate']) for need in NEEDS
    ]))
    write(tmp_path, 'catalog/targets.json', {'targets': {'fixture-target': dict(
        name='Fixture target', kind='soft', control_mode='bottom', source_species=['fixture-species'], habitat_kinds=[],
    )}})
    write(tmp_path, 'catalog/species.json', {'species': []})
    bounds = [-1, -1, 1, 1]
    write(tmp_path, 'catalog/coasts.json', dict(
        extra_targets={}, source_bindings={NEEDS[0]: SOURCE}, regions=[
            dict(id=ident, latitude=[4 - i, 5 - i], bounds=bounds, rules_url=URL, targets=[], watch=[], packages=[])
            for i, ident in enumerate(('northern', 'mendocino', 'san-francisco', 'central', 'southern'))
        ],
    ))
    ids = ('fixture-alpha', 'fixture-bravo')
    monkeypatch.setattr(build, 'DEFAULT_REGION', ids[0])
    write(tmp_path, 'dist/fixture-rules.json', {})
    for ident in ids:
        write(tmp_path, f'regions/{ident}/region.json', dict(
            schema_version=1, id=ident, name='Fixture coast', status='preview', timezone='Etc/UTC',
            bounds=bounds, fishing_bounds=bounds, jurisdiction='Fixture', jurisdiction_id='fixture-rules',
            boat=dict(name='Fixture boat', bottom_depth_limit_ft=100, cruise_knots=10),
            harbor=dict(name='Fixture harbor', latitude=0, longitude=0, information_url=URL, watch_keywords=[]),
            stations=dict(tide='0000000', airport='ZZZZ', nearshore_buoy='ZZZZZ', offshore_buoy='YYYYY',
                          nearshore_buoy_name='Nearshore', offshore_buoy_name='Offshore'),
            marine_zones=dict(coastal='ZZZ000', offshore='ZZZ001'),
            forecast_points=[dict(id='fixture-point', name='Fixture point', latitude=0, longitude=0)],
            species=['fixture-target'], source_bindings={need: [SOURCE] for need in NEEDS}, pipeline_sources={},
            assets={**{key: f'regions/{ident}/{key}.json' for key in ('atlas', 'habitats', 'bottom_index')},
                    'regulations': 'fixture-rules.json'},
            landing_names=[], mpa=dict(bounds=bounds, minimum_features=0), map={},
            coverage={need: dict(status='ready') for need in NEEDS}, coverage_note='Fixture coverage',
            intelligence=dict(regional_current_model='wcofs', wind_ensemble_model='gfs025',
                              wave_ensemble_provider='noaa-gefs',
                              providers=dict.fromkeys(('hfr', 'regional_current', 'wind_ensemble', 'wave_ensemble', 'spectra'), SOURCE),
                              verification_stations=[dict(id='ZZZZZ', latitude=0, longitude=0, source_url=URL)]),
        ))
    # Keep unrelated legal, spatial and browse products inert; real catalog, region,
    # coverage, directory, and serialization checks run on the private fixture tree.
    for name in ('validate_regional_rules', 'publish_shoreline', 'publish_depth_contours', 'publish_startup_forms',
                 'publish_land_water', 'compile_launch_points', 'compile_sectors', 'compile_readiness'):
        monkeypatch.setattr(build, name, lambda *args: None)
    return ids, source


def test_build_reads_once_and_keeps_its_snapshot(tmp_path, monkeypatch, synthetic_build):
    ids, source = synthetic_build
    dist = tmp_path / 'dist'

    def outputs():
        return {p.relative_to(dist): p.read_bytes() for p in dist.rglob('*') if p.is_file()}

    # Independent file-read observation, including reads via transitive callers.
    read_text = Path.read_text
    counts = Counter()
    expected = {'data-needs.json': 1, 'sources.json': 1}

    def count(path, *args, **kwargs):
        if path.parent == tmp_path / 'catalog' and path.name in expected:
            counts[path.name] += 1
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', count)
    assert [entry['id'] for entry in build.build(tmp_path)] == list(ids)
    baseline_reads = counts.copy()
    baseline = outputs()
    for ident in ids:
        coverage = json.loads(baseline[Path(f'regions/{ident}/coverage.json')])
        assert coverage['capabilities']['fixture-gate'] == {'ready': True, 'gaps': []}
        assert all(need['approved_sources'] == [SOURCE] for need in coverage['needs'])

    atomic_json = build.atomic_json
    first_report = dist / 'regions' / ids[0] / 'coverage.json'

    def after_first_region(path, value, **kwargs):
        result = atomic_json(path, value, **kwargs)
        if path == first_report:
            source['rights'].pop('commercial_use')
            write(tmp_path, 'catalog/sources.json', dict(schema_version=1, sources=[source]))
        return result

    counts.clear()
    monkeypatch.setattr(build, 'atomic_json', after_first_region)
    assert [entry['id'] for entry in build.build(tmp_path)] == list(ids)
    assert counts == baseline_reads == expected
    assert outputs() == baseline

    counts.clear()
    with pytest.raises(ValueError, match='Missing commercial-use review for fixture-source'):
        build.build(tmp_path)
    assert counts == expected
    assert outputs() == baseline

    # Standalone consumers still use fresh, validated catalog data.
    region = contracts.read_json(tmp_path / 'regions' / ids[0] / 'region.json')
    with pytest.raises(ValueError, match='Missing commercial-use review for fixture-source'):
        contracts.load_region(ids[0], tmp_path)
    with pytest.raises(ValueError, match='Missing commercial-use review for fixture-source'):
        contracts.requirement_report(region, tmp_path)
