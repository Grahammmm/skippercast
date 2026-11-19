"""F09-07: a finite forecast does not make an invalid mask cell water-supported."""
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.gis  # NumPy is installed in the survey tier, not core.


@pytest.fixture
def fetch_with_mask(monkeypatch):
    import numpy as np

    from skippercast.forecast import build
    from skippercast.forecast.models import Field, Model

    model = Model(id='test_mask', name='Test mask', provider='Test', kind='wind', family='gfs',
                  cycles=(0,), steps=(0,), fields=(Field('u10', ('UGRD', '10 m above ground'), 0.1),),
                  resolution_km=1, documentation='https://example.invalid', mask=('LAND', 'surface'))
    cycle = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(build, 'plan_step', lambda model, cycle, step, wanted: [(n, n, None) for n, _ in wanted])
    monkeypatch.setattr(build, 'download_all', lambda plan, workers: {n: blob for n, blob, _ in plan})
    monkeypatch.setattr(build, 'subset', lambda grid, lats, lons: (grid, lats, lons))

    def fetch(mask, *, resample=False):
        mask = np.asarray(mask, dtype=float)
        lons = np.arange(mask.shape[1], dtype=float)
        lats = np.array([0., 1., 2.] if resample else [0., 2.])
        field = np.full((len(lats), len(lons)), 5.)
        grids = {'u10': (field, lats, lons), '__mask__': (mask, np.array([0., 2.]), lons)}
        monkeypatch.setattr(build, 'decode', grids.__getitem__)
        return build.fetch_model(model, cycle, workers=4, log=lambda _: None)[3:]

    return fetch


@pytest.mark.parametrize('resample', [False, True], ids=['aligned', 'nearest-resampled'])
def test_finite_forecast_cannot_turn_invalid_mask_values_into_sea(fetch_with_mask, resample):
    # A bare < 0.5 test accepts the negative sentinel and -inf even with finite forecasts.
    cubes, sea = fetch_with_mask([[0., 0.49, 0.5, 1., -32768.],
                                  [float('nan'), float('inf'), -float('inf'), 1.1, 0.75]],
                                 resample=resample)
    assert (cubes['u10'] == 5.).all()
    water = [True, True, False, False, False]
    unsupported = [False] * 5
    assert sea.tolist() == ([water, unsupported, unsupported] if resample else [water, unsupported])


def test_valid_mask_preserves_land_and_water_at_threshold(fetch_with_mask):
    # Retain both sides of the cutoff and both inclusive endpoints of the valid fraction domain.
    _, sea = fetch_with_mask([[0., 0.49], [0.5, 1.]])
    assert sea.tolist() == [[True, True], [False, False]]


def test_all_invalid_mask_fails_instead_of_using_finite_forecast_as_support(fetch_with_mask):
    # An unusable supplied mask must not fall back to the maskless model rule.
    with pytest.raises(ValueError, match='land-sea mask has no valid fractions'):
        fetch_with_mask([[-32768., float('nan')], [-float('inf'), 1.1]])
