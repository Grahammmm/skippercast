"""Adapt already aligned native evidence to one tile of fine-proof bands."""

import numpy as np

from .fine_proof import NODATA, TILE
from .support_adapters import MEASURED


def prepare_bands(
    classes: np.ndarray,
    elevation: np.ndarray,
    native_spacing: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return class, positive-up elevation and native spacing for ``fine_proof.write``.

    All inputs must be real or boolean arrays on the same pre-aligned 256×256
    tile. Validity must be True (or numeric 1) to count. A masked sample in any
    array vetoes that cell regardless of its underlying value. No alignment or
    inference is performed; spacing is evidence, not the output pixel size.
    """
    inputs = (classes, elevation, native_spacing, valid)
    cls, elev, spacing, validity = data = tuple(np.ma.getdata(band) for band in inputs)
    if any(band.shape != (TILE, TILE) or band.dtype.kind not in 'biuf' for band in data):
        raise ValueError('each evidence band must be one real or boolean fine-proof tile')

    # Evaluate the original samples before casting to the writer's Float64 bands.
    # Nonfinite samples cannot satisfy these exact equalities or bounded ranges.
    keep = ((validity == 1) & (cls == MEASURED)
            & (elev >= -20) & (elev <= 0) & (spacing > 0) & (spacing <= 1))
    for band in inputs:
        keep &= ~np.ma.getmask(band)

    # Like the writer, do not round wider floating-point values on encoding.
    for band in (elev, spacing):
        if band.dtype.itemsize > np.dtype('float64').itemsize:
            samples = band[keep]
            keep[keep] = samples == samples.astype('float64')

    proof_class = np.full(keep.shape, NODATA)
    proof_elev = np.full(keep.shape, NODATA)
    proof_spacing = np.full(keep.shape, NODATA)
    proof_class[keep] = MEASURED
    proof_elev[keep] = elev[keep]
    proof_spacing[keep] = spacing[keep]
    return proof_class, proof_elev, proof_spacing
