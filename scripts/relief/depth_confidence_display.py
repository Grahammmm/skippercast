"""Review-only display of area shares from one depth coverage report band."""

from collections.abc import Mapping

_LABELS = ('measured', 'estimated', 'unsurveyed')


def format_band_shares(band: Mapping[str, int | float]) -> dict[str, str]:
    """Format the three area shares in a validated report band."""
    areas = {label: band[f'{label}_m2'] for label in _LABELS}
    total = sum(areas.values())
    if not total:
        return dict.fromkeys(_LABELS, 'n/a')

    shares = {}
    for label, area in areas.items():
        fraction = area / total
        # Compare before rounding: even 0.09% is below one display unit.
        if area == 0:
            shares[label] = '0.0%'
        elif fraction < 0.001:
            shares[label] = '<0.1%'
        else:
            shares[label] = f'{fraction * 100:.1f}%'
    return shares
