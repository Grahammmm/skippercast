"""Find the latest complete model cycle and download only the GRIB messages needed.

Both providers publish a per-file index: NOAA a text `.idx` (offset per message),
ECMWF a JSON-lines `.index` (offset and length). Each field is one HTTP range
request, so a run downloads megabytes per hour of forecast, not whole files.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import json
import random
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ECMWF_AWS, ECMWF_PORTAL, GFS_AWS

UA = 'SkipperCast-forecast-grids/1.0 (+https://github.com/Grahammmm/skippercast)'
RETRIES = 7


def http(url, byte_range=None, method='GET', timeout=60, retries=RETRIES):
    """GET (or HEAD) with retries. Returns bytes, or None for 404."""
    headers = {'User-Agent': UA}
    if byte_range:
        start, end = byte_range
        headers['Range'] = f'bytes={start}-' + ('' if end is None else str(end))
    delay = 2
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers=headers, method=method), timeout=timeout) as response:
                return b'' if method == 'HEAD' else response.read()
        except HTTPError as error:
            if error.code in (403, 404):
                return None
            if attempt == retries - 1:
                raise
        except (URLError, TimeoutError, ConnectionError, HTTPException):  # HTTPException: IncompleteRead on a cut transfer
            if attempt == retries - 1:
                raise
        # S3 answers bursts with 503 Slow Down; back off with jitter.
        time.sleep(delay + random.uniform(0, delay))
        delay = min(delay * 2, 30)
    return None


def exists(url):
    return http(url, method='HEAD', timeout=30) is not None


# ---- index parsing -------------------------------------------------------------

def parse_gfs_idx(text):
    """[(var, level, forecast, start, end_or_None)] from a NOAA .idx file."""
    rows = []
    lines = [line for line in text.splitlines() if line.strip()]
    for number, line in enumerate(lines):
        parts = line.split(':')
        start = int(parts[1])
        end = int(lines[number + 1].split(':')[1]) - 1 if number + 1 < len(lines) else None
        rows.append((parts[3], parts[4], parts[5], start, end))
    return rows


def select_gfs(rows, var, level):
    """Instantaneous message for VAR at LEVEL (not averages, accumulations or extremes)."""
    for name, lev, forecast, start, end in rows:
        if name == var and lev == level and not any(word in forecast for word in ('ave', 'acc', 'max', 'min')):
            return start, end
    return None


def parse_ecmwf_index(text):
    """{param: (start, end)} from an ECMWF JSON-lines .index file (surface/wave fields)."""
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('levtype', 'sfc') != 'sfc' and 'levelist' in row:
            continue
        out.setdefault(row['param'], (row['_offset'], row['_offset'] + row['_length'] - 1))
    return out


# ---- file locations ------------------------------------------------------------

def gfs_url(model, cycle, step, source='path'):
    path = model.extra[source].format(date=cycle.strftime('%Y%m%d'), hh=cycle.strftime('%H'), step=step)
    return f'{GFS_AWS}/{path}'


def ecmwf_url(model, cycle, step, base=ECMWF_AWS):
    stream = model.extra['stream']
    stamp = cycle.strftime('%Y%m%d%H0000')
    return f"{base}/{cycle:%Y%m%d}/{cycle:%H}z/ifs/0p25/{stream}/{stamp}-{step}h-{stream}-fc.grib2"


def index_url(model, cycle, step, base=ECMWF_AWS):
    if model.family == 'gfs':
        return gfs_url(model, cycle, step) + '.idx'
    return ecmwf_url(model, cycle, step, base)[:-len('.grib2')] + '.index'


def latest_cycle(model, now=None, lookback_hours=48):
    """Newest initialization whose final forecast step is published."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    for back in range(0, lookback_hours + 1):
        cycle = start - timedelta(hours=back)
        if cycle.hour not in model.cycles or cycle > now - timedelta(hours=model.cycle_delay_hours - 1):
            continue
        if exists(index_url(model, cycle, model.steps[-1])):
            return cycle
    return None


# ---- downloads -----------------------------------------------------------------

_ECMWF_BASE = {}


def ecmwf_base(model, cycle):
    """First ECMWF host that actually serves this cycle (the AWS mirror can refuse
    GETs from some networks while answering HEAD); cached per model and cycle."""
    key = (model.id, cycle)
    if key not in _ECMWF_BASE:
        for base in (ECMWF_AWS, ECMWF_PORTAL):
            try:
                if http(index_url(model, cycle, model.steps[-1], base), retries=2) is not None:
                    _ECMWF_BASE[key] = base
                    break
            except Exception:
                continue
        else:
            raise FileNotFoundError(f'{model.id} {cycle:%Y%m%d%H} unavailable from every ECMWF host')
    return _ECMWF_BASE[key]


def plan_step(model, cycle, step, want):
    """[(field_name, url, (start, end))] for one forecast step; missing fields omitted."""
    if model.family == 'gfs':
        plan = []
        for source in sorted({'native' if len(sel) > 2 and sel[2] == 'native' else 'path' for _, sel in want}):
            url = gfs_url(model, cycle, step, source)
            text = http(url + '.idx')
            if text is None:
                raise FileNotFoundError(f'{model.id} {cycle:%Y%m%d%H} f{step:03d} {source} index missing')
            rows = parse_gfs_idx(text.decode())
            for name, selector in want:
                if ('native' if len(selector) > 2 and selector[2] == 'native' else 'path') != source:
                    continue
                found = select_gfs(rows, *selector[:2])
                if found:
                    plan.append((name, url, found))
        return plan
    base = ecmwf_base(model, cycle)
    text = None
    for host in (base, ECMWF_PORTAL if base == ECMWF_AWS else ECMWF_AWS):
        try:
            text = http(index_url(model, cycle, step, host), retries=4)
        except Exception:
            text = None
        if text is not None:
            base = host
            break
    if text is None:
        raise FileNotFoundError(f'{model.id} {cycle:%Y%m%d%H} {step}h index missing')
    index = parse_ecmwf_index(text.decode())
    url = ecmwf_url(model, cycle, step, base)
    plan = []
    for name, selector in want:  # ECMWF selectors list alternative parameter names
        found = next((index[param] for param in selector if param in index), None)
        if found:
            plan.append((name, url, found))
    return plan


def mirror(url):
    """The same ECMWF file on the other host, or None for non-ECMWF URLs."""
    if url.startswith(ECMWF_AWS + '/'):
        return ECMWF_PORTAL + url[len(ECMWF_AWS):]
    if url.startswith(ECMWF_PORTAL + '/'):
        return ECMWF_AWS + url[len(ECMWF_PORTAL):]
    return None


def download_all(jobs, workers=16):
    """Fetch [(key, url, range)] in parallel -> {key: bytes}."""
    def one(job):
        key, url, byte_range = job
        try:
            data = http(url, byte_range, retries=4)
        except Exception:
            data = None
        if data is None:  # the other ECMWF host carries identical files
            alternate = mirror(url)
            if alternate is None:
                raise FileNotFoundError(url)
            data = http(alternate, byte_range)
            if data is None:
                raise FileNotFoundError(url)
        return key, data
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, jobs))
