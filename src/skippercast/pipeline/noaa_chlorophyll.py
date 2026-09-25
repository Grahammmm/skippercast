"""NOAA two-sensor near-real-time VIIRS chlorophyll; gaps remain missing."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import math
import re
from urllib.parse import urlencode
from xml.etree import ElementTree

from scipy.io import netcdf_file

HOST = "https://coastwatch.noaa.gov"
DIRECTORY = "chlociVIIRSnpp-n20GlobalDailyWW00"
CATALOG = f"{HOST}/thredds/catalog/{DIRECTORY}/catalog.xml"
FILENAME = re.compile(r"V(20\d{2})(\d{3})_D1_NPP-N20_WW00_chloci\.nc")


def latest_file(client):
    root = ElementTree.fromstring(client.get(CATALOG))
    found = []
    for entry in root.iter():
        path = entry.attrib.get("urlPath", "")
        if not path.startswith(DIRECTORY + "/"):
            continue
        match = FILENAME.fullmatch(path.rsplit("/", 1)[-1])
        if not match:
            continue
        day = datetime.strptime("-".join(match.groups()), "%Y-%j").replace(tzinfo=timezone.utc)
        if day <= client.now:
            found.append((day, path))
    if not found:
        raise ValueError("No dated NOAA VIIRS chlorophyll file in official catalog")
    day, path = max(found)
    if (client.now - day).total_seconds() > 120 * 3600:
        raise ValueError("Latest NOAA VIIRS chlorophyll file is stale")
    return day, path


def read_subset(body, bounds, path, day):
    if not body.startswith(b"CDF\x01"):
        raise ValueError("NOAA chlorophyll subset is not NetCDF classic")
    with netcdf_file(BytesIO(body), mmap=False) as nc:
        required = {"time", "lat", "lon", "altitude", "chl_oci"}
        if not required <= nc.variables.keys():
            raise ValueError("NOAA chlorophyll subset lacks required fields")
        t, lat, lon = (nc.variables[k][:].copy() for k in ("time", "lat", "lon"))
        chl = nc.variables["chl_oci"]
        if len(t) != 1 or len(lat) < 1 or len(lon) < 1 or chl.shape != (1, 1, len(lat), len(lon)):
            raise ValueError("NOAA chlorophyll axes changed")
        if chl.units != b"mg m^-3" or chl.standard_name != b"mass_concentration_of_chlorophyll_a_in_sea_water" or abs(float(chl._FillValue) + 32767) > .01:
            raise ValueError("NOAA chlorophyll units or fill value changed")
        if nc.variables["time"].units != b"seconds since 1970-01-01 00:00:00Z":
            raise ValueError("NOAA chlorophyll time units changed")
        sample = datetime.fromtimestamp(float(t[0]), timezone.utc)
        if not day <= sample < day + timedelta(days=1):
            raise ValueError("NOAA chlorophyll sample time conflicts with source filename")
        west, south, east, north = bounds["longitude"][0], bounds["latitude"][0], bounds["longitude"][1], bounds["latitude"][1]
        if not (-180 <= west < east <= 180 and -80 <= south < north <= 80):
            raise ValueError("Invalid regional chlorophyll bounds")
        rows = []
        values = chl[:].copy()
        for i, y in enumerate(lat):
            for j, x in enumerate(lon):
                y, x = float(y), float(x)
                if not (south - .04 <= y <= north + .04 and west - .04 <= x <= east + .04):
                    raise ValueError("NOAA chlorophyll cell outside requested bounds")
                raw = float(values[0, 0, i, j])
                value = round(raw, 5) if math.isfinite(raw) and .001 <= raw <= 100 else None
                rows.append({"time": sample.isoformat(timespec="seconds").replace("+00:00", "Z"),
                             "latitude": round(y, 5), "longitude": round(x, 5), "chlorophyll": value})
        if not rows:
            raise ValueError("Empty NOAA chlorophyll subset")
        return {"sample_at": sample.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "units": {"chlorophyll": "mg m-3"}, "valid_cells": sum(r["chlorophyll"] is not None for r in rows),
                "total_cells": len(rows), "samples": rows, "title": "NOAA VIIRS NPP/NOAA-20 OCI chlorophyll",
                "license": "NOAA public data; attribute NOAA CoastWatch", "kind": "chlorophyll",
                "native_resolution_degrees": [.0375, .0375], "dataset": path}


def fetch(client, bounds):
    day, path = latest_file(client)
    west, east = bounds["longitude"]
    south, north = bounds["latitude"]
    query = urlencode({"var": "chl_oci", "north": north, "south": south,
                       "west": west, "east": east, "accept": "netcdf"})
    url = f"{HOST}/thredds/ncss/grid/{path}?{query}"
    result = read_subset(client.get(url, as_binary=True), bounds, path, day)
    result.update(catalog_url=CATALOG, query_url=url, requested_bounds=bounds)
    return result
