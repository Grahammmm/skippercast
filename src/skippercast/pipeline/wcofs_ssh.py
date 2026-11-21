"""Offline conversion of a regional WCOFS zeta frame to SSH anomalies."""

import math

ZETA_UNITS = frozenset({"m", "meter", "meters"})


class WcofsSshError(ValueError):
    """The frame cannot be converted to SSH rows."""


def ssh_rows(latitudes, longitudes, zeta, units: str, fill_value=None) -> list[dict]:
    """Return valid cells in grid order, in centimetres relative to their mean."""
    cells = []
    try:
        if not isinstance(units, str) or units not in ZETA_UNITS:
            raise WcofsSshError("WCOFS zeta units must be metres")
        nx = len(longitudes)
        if len(zeta) != len(latitudes):
            raise WcofsSshError("WCOFS zeta shape does not match its axes")
        for axis in (latitudes, longitudes):
            # Integers are finite even when they cannot be converted to float.
            if not all(isinstance(coord, int) or math.isfinite(coord) for coord in axis):
                raise WcofsSshError("WCOFS zeta coordinates must be finite")

        for latitude, row in zip(latitudes, zeta, strict=True):
            if len(row) != nx:
                raise WcofsSshError("WCOFS zeta shape does not match its axes")
            for longitude, value in zip(longitudes, row, strict=True):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                if (isinstance(value, float) and not math.isfinite(value)) or value == fill_value:
                    continue
                if abs(value) > 20:
                    raise WcofsSshError("WCOFS zeta exceeds the 20 m limit")
                cells.append((latitude, longitude, value))
    except WcofsSshError:
        raise
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise WcofsSshError("Invalid WCOFS zeta frame") from exc

    if not cells:
        raise WcofsSshError("WCOFS zeta has no valid cells")

    mean = math.fsum(value for _, _, value in cells) / len(cells)
    return [
        {"latitude": latitude, "longitude": longitude, "ssh_cm": round((value - mean) * 100, 1)}
        for latitude, longitude, value in cells
    ]
