"""Project verified local SST inputs; never read a golden to supply input values."""

from argparse import Namespace
import json
import sys

import numpy as np


def prepare(kit, out):
    guide = kit / 'layers-style-guide'
    # The oracle owns projection and the fixture's water mask. Use only its
    # view geometry, not its SST sampler or any derived SST result.
    sys.path.insert(0, str(guide / 'reference'))
    try:
        from skl_render import Ctx

        ctx = Ctx(Namespace(tokens=None, stacking=None, base_tokens=None, now=None))
        layer = ctx.L('sst-fill')
        view = ctx.view(layer['view'], layer['zoom'])
    finally:
        sys.path.pop(0)
    with np.load(guide / 'fixtures/sst_mur.npz', allow_pickle=False) as source:
        source['sst_c'].astype('<f4').tofile(out / 'sst.f32')
        view.water.astype('<f4').tofile(out / 'water.f32')
        case = {
            'layer': 'sst-fill', 'view': layer['view'], 'zoom': layer['zoom'],
            'view_grid': {'lon': view.lon.tolist(), 'lat': view.lat.tolist(), 'mask': 'water.f32'},
            'source_grid': {'lon': source['lon'].tolist(), 'lat': source['lat'].tolist(), 'values': 'sst.f32'},
            'data_time_utc': source['time'].item(),
        }
    (out / 'case.json').write_text(json.dumps(case, sort_keys=True) + '\n')
