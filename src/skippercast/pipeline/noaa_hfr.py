"""Official NOAA NDBC HFRNet West Coast 6 km surface-current subset."""

from datetime import datetime, timezone
from io import BytesIO
import math
from urllib.parse import urlencode
from xml.etree import ElementTree

from scipy.io import netcdf_file

HOST = "https://dods.ndbc.noaa.gov"
DATASET = "hfradar_uswc_6km"
METADATA = f"{HOST}/thredds/ncss/grid/{DATASET}/dataset.xml"


def latest_time(client):
    root = ElementTree.fromstring(client.get(METADATA))
    span = root.find("TimeSpan")
    if span is None or span.findtext("end") is None:
        raise ValueError("NOAA HFRNet advertised time span missing")
    when = datetime.fromisoformat(span.findtext("end").replace("Z", "+00:00"))
    if when.tzinfo is None or when > client.now or (client.now - when).total_seconds() > 18 * 3600:
        raise ValueError("NOAA HFRNet advertised time is stale or future")
    axes = {a.attrib.get("name"): a for a in root.findall("axis")}
    try:
        lat = float(axes["lat"].find("values").attrib["resolution"])
        lon = float(axes["lon"].find("values").attrib["resolution"])
    except (AttributeError, KeyError, TypeError) as error:
        raise ValueError("NOAA HFRNet grid resolution missing") from error
    if not (.03 <= lat <= .08 and .03 <= lon <= .08):
        raise ValueError("NOAA HFRNet grid resolution changed")
    return when, [lat, lon]


def read_subset(body, bounds, expected_time, resolution):
    if not body.startswith(b"CDF\x01"):
        raise ValueError("NOAA HFRNet subset is not NetCDF classic")
    with netcdf_file(BytesIO(body), mmap=False) as nc:
        required = {"time", "lat", "lon", "u", "v", "number_of_sites", "hdop", "depth"}
        if not required <= nc.variables.keys():
            raise ValueError("NOAA HFRNet subset lacks required fields")
        t, lat, lon = (nc.variables[k][:].copy() for k in ("time", "lat", "lon"))
        u, v, n, hdop = (nc.variables[k] for k in ("u", "v", "number_of_sites", "hdop"))
        shape = (1, len(lat), len(lon))
        if len(t) != 1 or not len(lat) or not len(lon) or any(x.shape != shape for x in (u, v, n, hdop)):
            raise ValueError("NOAA HFRNet axes changed")
        if nc.variables["time"].units != b"seconds since 1970-01-01" or u.units != b"m s-1" or v.units != b"m s-1" or n.units != b"count":
            raise ValueError("NOAA HFRNet units changed")
        if u.standard_name != b"surface_eastward_sea_water_velocity" or v.standard_name != b"surface_northward_sea_water_velocity":
            raise ValueError("NOAA HFRNet vector semantics changed")
        sample = datetime.fromtimestamp(int(t[0]), timezone.utc)
        if sample != expected_time:
            raise ValueError("NOAA HFRNet returned time differs from advertised time")
        west, south, east, north = bounds["longitude"][0], bounds["latitude"][0], bounds["longitude"][1], bounds["latitude"][1]
        if not (-180 <= west < east <= 180 and -80 <= south < north <= 80):
            raise ValueError("Invalid NOAA HFRNet regional bounds")
        arrays = [x[:].copy() for x in (u, v, n, hdop)]
        rows = []
        for i, y in enumerate(lat):
            for j, x in enumerate(lon):
                y, x = float(y), float(x)
                if not (south - resolution[0] <= y <= north + resolution[0] and west - resolution[1] <= x <= east + resolution[1]):
                    raise ValueError("NOAA HFRNet cell outside requested bounds")
                eastward, northward, sites, dilution = (float(a[0, i, j]) for a in arrays)
                sites = int(sites) if 0 <= sites <= 100 else None
                valid = sites is not None and sites >= 2 and all(math.isfinite(vv) and abs(vv) <= 5 for vv in (eastward, northward))
                dilution = round(dilution, 4) if math.isfinite(dilution) and 0 <= dilution <= 100 else None
                rows.append({"time": sample.isoformat(timespec="seconds").replace("+00:00", "Z"),
                             "latitude": round(y, 5), "longitude": round(x, 5),
                             "water_u": round(eastward, 5) if valid else None,
                             "water_v": round(northward, 5) if valid else None,
                             "number_of_sites": sites, "hdop": dilution})
        if not rows:
            raise ValueError("Empty NOAA HFRNet subset")
        valid_count = sum(r["water_u"] is not None and r["water_v"] is not None for r in rows)
        return {"sample_at": sample.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "units": {"water_u": "m s-1", "water_v": "m s-1", "number_of_sites": "count", "hdop": "dimensionless"},
                "valid_cells": valid_count, "total_cells": len(rows), "samples": rows,
                "title": "NOAA HFRNet US West Coast hourly 6 km surface vectors",
                "license": "NOAA public data; attribute NOAA IOOS Surface Currents Program", "kind": "currents",
                "native_resolution_degrees": resolution, "dataset": DATASET,
                "nominal_depth_m": float(nc.variables["depth"].data.item())}


def fetch(client, bounds):
    when, resolution = latest_time(client)
    west, east = bounds["longitude"]
    south, north = bounds["latitude"]
    query = urlencode({"var": ["u", "v", "number_of_sites", "hdop"],
                       "north": north, "south": south, "west": west, "east": east,
                       "time": when.isoformat(timespec="seconds").replace("+00:00", "Z"),
                       "accept": "netcdf"}, doseq=True)
    url = f"{HOST}/thredds/ncss/grid/{DATASET}?{query}"
    result = read_subset(client.get(url, as_binary=True), bounds, when, resolution)
    result.update(metadata_url=METADATA, query_url=url, requested_bounds=bounds)
    return result
