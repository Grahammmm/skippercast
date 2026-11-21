"""Read one cycle of WCOFS zeta subsets through an injected client."""

import re
from datetime import datetime

from .ocean import dap
from .wcofs_zeta import zeta_contract, zeta_query, zeta_rows


class WcofsZetaFramesError(ValueError):
    """The requested subset or forecast steps cannot form WCOFS zeta frames."""


def zeta_frames(
    client,
    base: str,
    files: list[str],
    cycle: datetime,
    time_origin: datetime,
    time_factor: int,
    y0: int,
    y1: int,
    x0: int,
    x1: int,
    latitudes: list,
    longitudes: list,
) -> list[dict]:
    """Load contract-checked, stride-one zeta frames for the supplied axes."""
    if not files:
        raise WcofsZetaFramesError("No WCOFS forecast steps supplied")
    first = base + files[0]
    meta = zeta_contract(client.get(first + ".dds"), client.get(first + ".das"))
    ny, nx = y1 - y0 + 1, x1 - x0 + 1
    if y1 >= meta["ny"] or x1 >= meta["nx"] or len(latitudes) != ny or len(longitudes) != nx:
        raise WcofsZetaFramesError("WCOFS zeta subset does not match the grid or axes")

    forecast = []
    for file in files:
        match = re.search(r"\.f(\d{3})\.nc$", file)
        if match:
            hour = int(match[1])
            if 0 <= hour <= 72 and hour % 3 == 0:
                forecast.append((hour, file))
    if not forecast:
        raise WcofsZetaFramesError("No WCOFS forecast steps supplied")

    query = zeta_query(y0, y1, x0, x1) + ",time"
    origin = time_origin.timestamp()
    issued = cycle.timestamp()
    frames = []
    for hour, file in sorted(forecast, key=lambda step: step[0]):
        arrays = dap(client, base + file, query)
        rows = zeta_rows(arrays.get("zeta", []), ny, nx)
        times = arrays.get("time", [])
        if len(times) != 1:
            raise WcofsZetaFramesError(f"Expected one WCOFS time value in {file}")
        when = origin + times[0] * time_factor
        if not abs(when - (issued + hour * 3600)) <= 60:
            raise WcofsZetaFramesError(f"WCOFS valid time disagrees with cycle in {file}")
        frames.append({
            "time": int(when),
            "latitudes": latitudes,
            "longitudes": longitudes,
            "zeta": rows,
            "units": meta["units"],
            "fill_value": meta["fill_value"],
            "source_file": file,
        })
    return sorted(frames, key=lambda frame: frame["time"])
