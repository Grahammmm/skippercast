"""Non-GIS refusals and exact documented argv for B1b."""
import ast
import copy
from pathlib import Path
import socket

import pytest

from tests.coast_admit_factory import COMMANDS, ROOT, common, refs, stage, world


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args,**kwargs):
        raise AssertionError('B1b may not open a socket')
    monkeypatch.setattr(socket,'socket',refuse)
    monkeypatch.setattr(socket,'create_connection',refuse)
    monkeypatch.setattr(socket,'getaddrinfo',refuse)


def test_documented_exact_command_contract():
    text = (ROOT/'skills/coast-segment-admit/SKILL.md').read_text()
    lines = [line for line in text.splitlines() if line.startswith(('"$SC_PY"','PYTHONPATH=src "$SC_PY"'))]
    assert lines == list(COMMANDS)  # byte-for-byte spellings, not approximate flags
    discover = (ROOT/'skills/coast-segment-discover/SKILL.md').read_text()
    assert 'PYTHONPATH=src "$SC_PY" -m skippercast.coastal.live_discovery dry-run --plan "$D/plan.json" --out "$D/dry"' in discover
    assert 'PYTHONPATH=src "$SC_PY" -m skippercast.coastal.live_discovery run --plan "$D/plan.json" --out "$D/run"' in discover
    for name in ('coast-segment-discover','coast-segment-admit'):
        text = (ROOT/'skills'/name/'SKILL.md').read_text()
        for heading in ('Purpose','Runs on','Inputs','Exact commands','Acceptance checks','Failure modes','Metrics emitted','Never'):
            assert '# '+heading in text


def test_stage_validates_hash_caps_and_copies_not_links(tmp_path):
    w = world(tmp_path)
    result = stage(w)
    assert result['holds'] == [] and result['network_requests'] == 0
    ref = result['sources'][0]['hot_cache']
    assert ref['sha256'] == w['selection']['windows'][0]['input']['sha256']
    path = w['queue']/ref['path']
    assert path.read_bytes() == (w['raw']/'input0.tif').read_bytes()
    assert path.stat().st_nlink == 1
    assert path.stat().st_ino != (w['raw']/'input0.tif').stat().st_ino
    assert 'ncei:' not in ref['path']
    with pytest.raises(ValueError,match='already exists'):
        stage(w)


@pytest.mark.parametrize('failure',['hash','catalog-hash','cap','per-job','miss','hardlink','symlink','derived','roots','raw-binding'])
def test_staging_refuses_before_any_cache_copy(tmp_path,failure):
    w = world(tmp_path)
    sel = w['selection']
    if failure == 'hash':
        (w['raw']/'input0.tif').write_bytes(b'X'*(w['raw']/'input0.tif').stat().st_size)
    elif failure == 'catalog-hash':
        sel['windows'][0]['input']['sha256'] = 'f'*64
    elif failure == 'cap':
        sel['max_total_bytes'] = 1
    elif failure == 'per-job':
        sel['budget']['bytes'] = 1
    elif failure == 'miss':
        (w['raw']/'input0.tif').unlink()
    elif failure == 'hardlink':
        (w['raw']/'alias.tif').hardlink_to(w['raw']/'input0.tif')
    elif failure == 'symlink':
        (w['raw']/'input0.tif').rename(w['raw']/'other.tif')
        (w['raw']/'input0.tif').symlink_to(w['raw']/'other.tif')
    elif failure == 'derived':
        (w['queue']/'derived.tif').write_bytes(b'derived')
        sel['windows'][0]['input'] = common.file_ref(w['queue']/'derived.tif','queue:synthetic-campaign',w['queue'])
    elif failure == 'roots':
        Path(w['env']['ROOTS']).write_bytes(refs.canonical({'raw:campaign':str(w['raw'])}))
    elif failure == 'raw-binding':
        raw = refs.loads(Path(w['env']['RAW_RECEIPT']).read_bytes())
        raw['sources'] = []
        w['put'](Path(w['env']['RAW_RECEIPT']),raw)
    if failure != 'raw-binding':
        w['put'](Path(w['env']['SELECTION']),sel)
        raw = refs.loads(Path(w['env']['RAW_RECEIPT']).read_bytes())
        raw['sources'] = [{k:x[k] for k in ('source_id','input','raw_provenance','retained_inputs')} for x in sel['windows']]
        w['put'](Path(w['env']['RAW_RECEIPT']),raw)
    with pytest.raises((ValueError,OSError,KeyError)):
        stage(w)
    assert not (w['queue']/'cache').exists()
    assert not Path(w['env']['CACHE_STAGE_RECEIPT']).exists()


@pytest.mark.parametrize(('x','y','expected'),[(0,0,'seg:3310:0:0:5000'),(-0.1,-0.1,'seg:3310:-5000:-5000:5000'),
    (-5000,-5000,'seg:3310:-5000:-5000:5000'),(5000,-5000.1,'seg:3310:5000:-10000:5000')])
def test_half_open_centre_owner_negative_boundary(x,y,expected):
    assert common.owner_id(x,y) == expected


@pytest.mark.parametrize('change',[lambda s:s['windows'].append(copy.deepcopy(s['windows'][0])),
    lambda s:s['windows'][0]['grid_definition'].update(tiling_version='unreviewed-PC6'),
    lambda s:s['windows'][0].update(reader='invented-reader'),
    lambda s:s['windows'][0].update(pixel_window=[0,0,1024,1024])])
def test_duplicate_grid_reader_and_cap_refusal(tmp_path,change):
    w = world(tmp_path)
    change(w['selection'])
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    with pytest.raises(ValueError):
        stage(w)


def test_no_downloader_imports():
    forbidden = {'socket','requests','httpx','urllib.request','http.client','skippercast.coastal.live_discovery'}
    for path in (ROOT/'skills/coast-segment-admit/scripts').glob('*.py'):
        names = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom):
                names.add(node.module)
        assert not names & forbidden


def test_relative_argument_refusal():
    with pytest.raises(ValueError,match='absolute'):
        common.read_json(Path('campaign.json'))


def test_derived_without_lineage_refuses_explicitly(tmp_path):
    w = world(tmp_path)
    window = copy.deepcopy(w['selection']['windows'][0])
    original = w['raw']/'original.bag'
    original.write_bytes(b'synthetic original, distinct from derived input')
    window['raw_provenance'] = [common.file_ref(original,'raw:campaign',w['raw'])]
    resolver = common.resolver_for(Path(w['env']['ROOTS']),w['selection'],w['queue'],'queue:synthetic-campaign')
    with pytest.raises(ValueError,match='derivation lineage'):
        common.verify_provenance(window,resolver)


@pytest.mark.parametrize('field',['code_commit','skill_commit'])
def test_checkout_pin_mismatch_refuses_before_copy(tmp_path,field):
    w = world(tmp_path)
    w['selection'][field] = 'a'*40
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    with pytest.raises(ValueError,match='pinned checkout'):
        stage(w)
    assert not (w['queue']/'cache').exists()


def test_symlink_parent_refuses_before_copy(tmp_path):
    w = world(tmp_path)
    (w['queue']/'cache').symlink_to(w['raw'],target_is_directory=True)
    with pytest.raises(OSError):
        stage(w)
    assert sorted(p.name for p in w['raw'].iterdir()) == ['input0.tif']


def test_changed_canonical_campaign_encoding_refuses(tmp_path):
    import json
    w = world(tmp_path)
    (w['queue']/'campaign.json').write_text(json.dumps(w['campaign'],indent=2))
    with pytest.raises(ValueError,match='exact canonical'):
        stage(w)


def test_unknown_intermediate_selection_field_refuses(tmp_path):
    w = world(tmp_path)
    w['selection']['unreviewed_override'] = True
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    with pytest.raises(ValueError,match='selection field'):
        stage(w)


def test_unbound_raw_tiff_sidecar_not_silently_lost(tmp_path):
    w = world(tmp_path)
    (w['raw']/'input0.tif.aux.xml').write_bytes(b'<synthetic-aux/>')
    with pytest.raises(ValueError,match='sidecar'):
        stage(w)
    assert not (w['queue']/'cache').exists()
