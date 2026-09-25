"""Bounded official NOAA blended SST via THREDDS NetCDF Subset Service."""

from datetime import datetime, timezone
from io import BytesIO
import math
import re
from urllib.parse import urlencode
from xml.etree import ElementTree

from scipy.io import netcdf_file

HOST = "https://coastwatch.noaa.gov"
PATH = "Blended/SST5km/Night/GHRSSTOSPO"
FILE = re.compile(r"(20\d{12})-OSPO-L4_GHRSST-SSTfnd-Geo_Polar_Blended_Night-GLOB-v02\.0-fv01\.0\.nc$")
CATALOG = f"{HOST}/thredds/catalog/{PATH}"


def latest_file(client, now):
    found = []
    for year in (now.year, now.year - 1):
        url = f"{CATALOG}/{year}/catalog.xml"
        root = ElementTree.fromstring(client.get(url))
        for entry in root.iter():
            path = entry.attrib.get("urlPath", "")
            match = FILE.fullmatch(path.rsplit("/", 1)[-1])
            if match and path == f"{PATH}/{year}/{match.group(0)}":
                date = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                if date <= now:
                    found.append((date, path, url))
        if found:
            break
    if not found:
        raise ValueError("No dated NOAA blended SST file in official catalog")
    date, path, url = max(found)
    if (now - date).total_seconds() > 96 * 3600:
        raise ValueError("Latest NOAA blended SST file is stale")
    return path, url


def read_subset(body, bounds, path):
    if not body.startswith(b"CDF\x01"):
        raise ValueError("NOAA subset is not NetCDF classic")
    with netcdf_file(BytesIO(body), mmap=False) as nc:
        required = {"time", "lat", "lon", "analysed_sst", "analysis_error", "mask"}
        if not required <= nc.variables.keys():
            raise ValueError("NOAA SST subset lacks required fields")
        t, lat, lon = (nc.variables[k][:].copy() for k in ("time", "lat", "lon"))
        temp = nc.variables["analysed_sst"]
        err = nc.variables["analysis_error"]
        mask = nc.variables["mask"]
        if len(t) != 1 or len(lat) < 1 or len(lon) < 1 or temp.shape != (1, len(lat), len(lon)) or err.shape != temp.shape or mask.shape != temp.shape:
            raise ValueError("NOAA SST axes changed")
        if temp.units != b"kelvin" or err.units != b"kelvin" or temp.scale_factor != .01 or err.scale_factor != .01 or abs(temp.add_offset - 273.15) > .001 or mask.flag_values.tolist() != [1, 2, 4]:
            raise ValueError("NOAA SST scale, units or mask changed")
        if not str(nc.variables["time"].units).startswith("b'seconds since 1981-01-01"):
            raise ValueError("NOAA SST time units changed")
        sample = datetime.fromtimestamp(datetime(1981, 1, 1, tzinfo=timezone.utc).timestamp() + int(t[0]), timezone.utc)
        sample_at = sample.isoformat(timespec="seconds").replace("+00:00", "Z")
        west, south, east, north = bounds["longitude"][0], bounds["latitude"][0], bounds["longitude"][1], bounds["latitude"][1]
        rows = []
        raw_t, raw_e, raw_m = (v[:].copy() for v in (temp, err, mask))
        for i, y in enumerate(lat):
            for j, x in enumerate(lon):
                y, x = float(y), float(x)
                if not (south - .05 <= y <= north + .05 and west - .05 <= x <= east + .05):
                    raise ValueError("NOAA SST cell outside requested bounds")
                a, e, m = int(raw_t[0, i, j]), int(raw_e[0, i, j]), int(raw_m[0, i, j])
                valid = m == 1 and a != -32768 and -200 <= a <= 4000
                c = round(a * .01, 3) if valid else None
                error = round(e * .01, 3) if valid and e != -32768 and 0 <= e <= 500 else None
                rows.append({"time": sample_at, "latitude": round(y, 5), "longitude": round(x, 5), "analysed_sst": c, "analysis_error": error, "mask": m})
        if not rows or not any(r["analysed_sst"] is not None for r in rows):
            raise ValueError("NOAA SST subset has no open-water cells")
        return {"sample_at": sample_at, "metadata_created_at": getattr(nc, "date_created", b"").decode(),
                "units": {"analysed_sst": "degree_C", "analysis_error": "degree_C", "mask": "flag"},
                "valid_cells": sum(r["analysed_sst"] is not None for r in rows), "total_cells": len(rows),
                "samples": rows, "title": getattr(nc, "title", b"NOAA blended SST").decode(),
                "license": "free/open GHRSST; attribute NOAA CoastWatch", "kind": "sst",
                "native_resolution_degrees": [.05, .05], "dataset": path}


def fetch(client, bounds):
    path, catalog_url = latest_file(client, client.now)
    west, east = bounds["longitude"]
    south, north = bounds["latitude"]
    if not (-180 <= west < east <= 180 and -80 <= south < north <= 80):
        raise ValueError("Invalid NOAA SST regional bounds")
    query = urlencode({"var": ["analysed_sst", "analysis_error", "mask"], "north": north,
                       "south": south, "west": west, "east": east, "accept": "netcdf"}, doseq=True)
    url = f"{HOST}/thredds/ncss/grid/{path}?{query}"
    result = read_subset(client.get(url, as_binary=True), bounds, path)
    result.update(catalog_url=catalog_url, query_url=url, requested_bounds=bounds)
    return result
