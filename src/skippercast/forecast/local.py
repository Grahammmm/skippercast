"""Sample SkipperCast forecast tiles from Python, exactly as the Worker does.

The pipeline runs the shared JavaScript sampler (`scripts/model_api.mjs`) with
Node, so pipeline samples and app responses can never disagree. Tiles come from
a local directory (`SKIPPERCAST_FORECAST_ROOT`, set by the live job after it
builds them) or, elsewhere, from the published `forecasts` branch.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parents[3]
FEED = 'https://raw.githubusercontent.com/Grahammmm/skippercast/forecasts'
API = 'https://skippercast.com/api/om'
MARINE = {'ncep_gfswave016', 'ecmwf_wam'}


def kind_of(model):
    return 'marine' if model in MARINE else 'forecast'


def public_url(model, params):
    """The equivalent public query, recorded as each source's provenance URL."""
    return f"{API}/v1/{kind_of(model)}?{urlencode(params)}"


def meta_url(model):
    return f'{API}/data/{model}/static/meta.json'


def local_root():
    root = os.environ.get('SKIPPERCAST_FORECAST_ROOT')
    return Path(root) if root and Path(root, 'index.json').is_file() else None


def _stage(client, models, points, root):
    """Download the manifests and tiles these points need into `root`."""
    for model in models:
        manifest = client.get(f'{FEED}/{model}/manifest.json', True)
        (root / model / 'tiles').mkdir(parents=True, exist_ok=True)
        (root / model / 'manifest.json').write_text(json.dumps(manifest))
        for key in sorted({f'{math.floor(lat)}_{math.floor(lon)}' for lat, lon in points}):
            if key in manifest.get('tiles', []):
                tile = client.get(f'{FEED}/{model}/tiles/{key}.json', True)
                (root / model / 'tiles' / f'{key}.json').write_text(json.dumps(tile))


def run_sampler(root, kind, query, now=None):
    env = {**os.environ, **({'SKIPPERCAST_NOW': str(int(now))} if now is not None else {})}
    result = subprocess.run(['node', str(REPO / 'scripts/model_api.mjs'), str(root), kind, query],
                            capture_output=True, text=True, timeout=120, env=env)
    data = json.loads(result.stdout or '{}')
    if result.returncode != 0 or (isinstance(data, dict) and data.get('error')):
        raise ValueError('Forecast sampler: ' + (data.get('reason') if isinstance(data, dict) else result.stderr[-300:]))
    return data


def sample(model, params, client=None):
    """Open-Meteo-shaped response for one model from SkipperCast tiles."""
    points = list(zip(map(float, str(params['latitude']).split(',')), map(float, str(params['longitude']).split(','))))
    query = urlencode({**params, 'models': model})
    root = local_root()
    if root:
        return run_sampler(root, kind_of(model), query)
    if client is None:
        raise ValueError('No local forecast tiles and no client to fetch published ones')
    with tempfile.TemporaryDirectory() as staging:
        _stage(client, [model], points, Path(staging))
        return run_sampler(Path(staging), kind_of(model), query)


def meta(model, client=None):
    """Open-Meteo-shaped meta.json for one model."""
    root = local_root()
    if root:
        manifest = json.loads((root / model / 'manifest.json').read_text())
    elif client is not None:
        manifest = client.get(f'{FEED}/{model}/manifest.json', True)
    else:
        raise ValueError('No local forecast tiles and no client to fetch published ones')
    return {**manifest['meta'], 'provider': manifest['provider'], 'cycle_iso': manifest['cycle_iso']}
