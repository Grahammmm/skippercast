"""Offline metadata checks and subset helpers for the WCOFS zeta field."""

import re

from .habitat_dynamics import _block
from .wcofs_ssh import ZETA_UNITS


class WcofsZetaContractError(ValueError):
    """The WCOFS zeta metadata or subset failed a contract check."""


def zeta_contract(dds: str, das: str) -> dict:
    """Validate zeta against the regular grid and return its read metadata."""
    declarations = list(re.finditer(r"\bzeta\[time = 1\]\[ny = (\d+)\]\[nx = (\d+)\]\s*;", dds))
    if len(declarations) != 1:
        raise WcofsZetaContractError("Expected one WCOFS zeta DDS declaration with time=1, ny, nx")
    declaration = declarations[0]
    ny, nx = map(int, declaration.groups())
    # Do not let zeta itself overwrite the grid dimensions being checked.
    grid_dds = dds[:declaration.start()] + dds[declaration.end():]
    dims = {k: int(v) for k, v in re.findall(r"\[(ny|nx) = (\d+)\]", grid_dds)}
    if dims != {"ny": ny, "nx": nx}:
        raise WcofsZetaContractError("WCOFS zeta ny/nx do not match the DDS grid dimensions")

    try:
        block = _block(das, "zeta")
    except ValueError as exc:
        raise WcofsZetaContractError(str(exc)) from exc
    units = re.search(r'(?:^|;)\s*String\s+units\s+"([^"]*)"\s*;', block)
    if units is None or units[1] not in ZETA_UNITS:
        raise WcofsZetaContractError("WCOFS zeta units must be metres")
    long_name = re.search(r'(?:^|;)\s*String\s+long_name\s+"((?:[^"\\]|\\.)*)"\s*;', block)
    if long_name is not None and "free-surface" not in long_name[1].lower():
        raise WcofsZetaContractError("WCOFS zeta long_name must describe the free-surface")
    fill = re.search(r"(?:^|;)\s*\w+\s+_FillValue\b([^;]*);", block)
    try:
        fill_value = float(fill[1]) if fill is not None else None
    except ValueError as exc:
        raise WcofsZetaContractError("WCOFS zeta _FillValue must be numeric") from exc
    return {"units": units[1], "fill_value": fill_value, "ny": ny, "nx": nx}


def zeta_query(y0: int, y1: int, x0: int, x1: int) -> str:
    """Build the inclusive, stride-one subset constraint for one frame."""
    for name, index in (("y0", y0), ("y1", y1), ("x0", x0), ("x1", x1)):
        if not isinstance(index, int) or isinstance(index, bool):
            raise WcofsZetaContractError(f"WCOFS zeta index {name} must be an integer")
        if index < 0:
            raise WcofsZetaContractError(f"WCOFS zeta index {name} must be nonnegative")
    if y0 > y1 or x0 > x1:
        raise WcofsZetaContractError("WCOFS zeta subset bounds must be ordered (y0 <= y1, x0 <= x1)")
    return f"zeta[0][{y0}:1:{y1}][{x0}:1:{x1}]"


def zeta_rows(values, ny: int, nx: int) -> list[list]:
    """Split row-major DAP values into rows without altering the cells."""
    if ny < 1 or nx < 1:
        raise WcofsZetaContractError("WCOFS zeta row dimensions ny and nx must be at least 1")
    if len(values) != ny * nx:
        raise WcofsZetaContractError("WCOFS zeta value count must equal ny * nx")
    return [list(values[start:start + nx]) for start in range(0, ny * nx, nx)]
