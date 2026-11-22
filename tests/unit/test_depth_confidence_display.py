"""Synthetic controls for review-only depth confidence copy."""

from types import MappingProxyType

from scripts.relief.depth_confidence_display import format_band_shares


def test_tiny_positive_differs_from_true_zero():
    """Plain rounding would hide the tiny area; flooring would mislabel zero."""
    band = MappingProxyType(dict(measured_m2=9999.0, estimated_m2=1.0, unsurveyed_m2=0.0))
    assert format_band_shares(band) == {
        'measured': '100.0%',
        'estimated': '<0.1%',
        'unsurveyed': '0.0%',
    }


def test_display_boundary_uses_unrounded_share():
    """Testing after rounding hides 0.09%; an inclusive cutoff mislabels 0.1%."""
    band = dict(measured_m2=10.0, estimated_m2=9981.0, unsurveyed_m2=9.0)
    assert format_band_shares(band) == {
        'measured': '0.1%',
        'estimated': '99.8%',
        'unsurveyed': '<0.1%',
    }


def test_zero_band_total_is_unavailable():
    """Handling zero areas before the denominator could report three false zeros."""
    band = dict(measured_m2=0.0, estimated_m2=0.0, unsurveyed_m2=0.0)
    assert format_band_shares(band) == {
        'measured': 'n/a',
        'estimated': 'n/a',
        'unsurveyed': 'n/a',
    }
