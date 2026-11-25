"""Exercise the offline byte join with producer-valid proof and envelope fixtures."""
import base64
import json
import zlib

import pytest

from scripts.relief import fine_lineage_manifest
from skippercast.relief import package, receipts
from tests.unit.test_r8_packet_compare import _candidate
from tests.unit.test_relief_package import assembly, sha  # noqa: F401 (assembly fixture)

# Packed synthetic GeoTIFFs from fine_proof.write: one 256px tile at XYZ (z, 1, 1),
# class 3, spacing 1 m, depth -10 m (-11 m for the alternate z16). Baked so
# the test needs no survey stack. The SHA-256 values are from RMSC-90 --json.
Z16 = (
    'a37d997e5862299163937985a9fdddf170fd03e9ba3ba95e03856f18392b6971',
    'eNrz9NRi4GBgYBBhYGBkZmAEskAEIxKbCchmBjL/ATEzVBykgw3KBmFRKBukTgZJ3BaJ7YRkpjMS'
    '24WRBcyWY2JgcIWyffgZGIKAapgYICAY6gYWoCRfMw+YnQdkN7XwMLAB2W1A9vp2ZgYFIHsbkL2x'
    'nYlBEcj+BmQ3LGFiSAGyuYDsRiAbpF4CarADGDKDoY27i6OPb2pJYkpiSaIdl4KCjWdJaq5CXmJu'
    'qq1ScXJ8WmZeanxBUX5+mpKdoY0+SBJdVVV+fi5Q0gwma6OPaibDZIEa1x/SzA4wmoEAmN3azXtJ'
    'uvgglHaEiTOCQ4kdGCAQNiOUZmLZ2C4JkufY2M7OIMnAxgES71Nm4AHRgvwsYFpTOdw9WMHCREFf'
    'IaA4tTQlX9c3tSg5sSS/qAYiUcPAoGsJBAwVc96cMGRkUBBgWCjNm8Tfm6eiXCMosXJV6eqs/at+'
    'Ha9+v/f7vVFilBhWhP2bE4rgwmnC//Wyir/+j4JRMOxAsjsfJyiNN/ypf8txcTQ8RsHwA/LWRR7g'
    '5tKT/9nuHf9GA2QUDD9wY6IzuDOj8D/e2unLaHiMguEHrvfJCIHSOMev/7eE3ToqhlaH4vdrZpGP'
    'ymEAzK6OoQ==',
)
Z17 = (
    '6591df049a4f18a48b01d3d66aed5e3ad6c0464d00b73efdcb8d79a83432fa55',
    'eNrz9NRi4GBgYBBhYGBkZmAEskAEIxKbCchmBjL/ATEzVBykgw3KBmFRKBukTgZJ3BaJ7YRkpjMS'
    '24WRBcyWY2JgcIWyffgZGIKAapgYICAY6gYWoCRfMw+YnQdkN7XwMLAB2W1A9vp2ZgYFIHsbkL2x'
    'nYlBEcj+BmQ3LGFiSAGyuYDsRiAbpF4CarADGDKDoY27i6OPb2pJYkpiSaIdl4KCjWdJaq5CXmJu'
    'qq1ScXJ8WmZeanxBUX5+mpKdoY0+SBJdVVV+fi5Q0hwma6OPaibDZIEa1x/Sn+1hNAMBIH66WfOp'
    'dPFBKO0IE2cEhxI7MEAgbEYozcSysV0SJM+xsZ2dQZKBjQMk3qfMwAOiBflZwLSmcrh7sIKFiYK+'
    'QkBxamlKvq5valFyYkl+UQ1EooaBQdcSCBgq5rw5YcjIoCDAsFCaN4m/N09FuUZQYuWq0tVZ+1f9'
    'Ol79fu/3e6PEKDGsCPs3JxTBhdOE/+tlFX/9HwWjYNiBZHc+TlAab/hT/5bj4mh4jILhB+StizzA'
    'zaUn/7PdO/6NBsgoGH7gxkRncGdG4X+8tdOX0fAYBcMPXO+TEQKlcY5f/28Ju3VUDK0Oxe/XzCIf'
    'lcMAzJuQUg==',
)
OTHER_Z16 = (
    'dc569dd6948fd51a0daab389f87136cdb1310f8927e4ff809adba63a0f4fa369',
    'eNrz9NRi4GBgYBBhYGBkZmAEskAEIxKbCchmBjL/ATEzVBykgw3KBmFRKBukTgZJ3BaJ7YRkpjMS'
    '24WRBcyWY2JgcIWyffgZGIKAapgYICAY6gYWoCRfMw+YnQdkN7XwMLAB2W1A9vp2ZgYFIHsbkL2x'
    'nYlBEcj+BmQ3LGFiSAGyuYDsRiAbpF4CarADGDKDoY27i6OPb2pJYkpiSaIdl4KCjWdJaq5CXmJu'
    'qq1ScXJ8WmZeanxBUX5+mpKdoY0+SBJdVVV+fi5Q0gwma6OPaibDZIEa1x/SzA4wmoEAmN3azXtJ'
    'uvgglHaEiTOCQ4kdGCAQNiOUZmLZ2C4JkufY2M7OIMnAxgES71Nm4AHRgvwsYFpTOdw9WMHCREFf'
    'IaA4tTQlX9c3tSg5sSS/qAYiUcPAoGsJBAwVc96cMGRkUBBgWCjtm8Tbm6eiXCMosXJV6eqs/at+'
    'Ha9+v/f7vVFilBhWhP2bE4rgwmnC//Wyir/+j4JRMOxAsjsfJyiNN/ypf8txcTQ8RsHwA/LWRR7g'
    '5tKT/9nuHf9GA2QUDD9wY6IzuDOj8D/e2unLaHiMguEHrvfJCIHSOMev/7eE3ToqhlaH4vdrZs2z'
    'yiUAfnSO7g==',
)


def _raster(path, fixture):
    path.write_bytes(zlib.decompress(base64.b64decode(fixture[1])))
    return path


def _row(zoom, fixture):
    return dict(zoom=zoom, raster_sha256=fixture[0], tile_range=dict(x0=1, y0=1, x1=1, y1=1),
                certified=1, uncertified=0, unproven=0, certified_tiles=[f'{zoom}/1/1'])


@pytest.fixture
def inputs(tmp_path, assembly):
    review = _candidate(tmp_path / 'fixture-region')
    summary = tmp_path / 'proof-report.json'
    summary.write_text(json.dumps([_row(16, Z16), _row(17, Z17)]) + '\n', encoding='utf-8')
    return (summary, review, _raster(tmp_path / 'z16.tif', Z16), _raster(tmp_path / 'z17.tif', Z17))


def _run(summary, review, z16, z17):
    args = ['--summary', str(summary), '--envelope', str(review)]
    for flag, path in [('--z16', z16), ('--z17', z17)]:
        if path is not None:
            args.extend([flag, str(path)])
    return fine_lineage_manifest.main(args)


def test_valid_join_is_stdout_only_and_not_approval(inputs, tmp_path, capsys):
    """Bind exact bytes, not parsed JSON or filenames; catch writes or requiring approval."""
    summary, review, z16, z17 = inputs

    def snapshot():
        return {p: (p.stat().st_mtime_ns, sha(p) if p.is_file() else None)
                for p in [tmp_path, *tmp_path.rglob('*')]}

    before = snapshot()
    assert _run(*inputs) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    assert not err and report['status'] == 'complete'
    assert report['summary_sha256'] == sha(summary)
    assert report['envelope_sha256'] == sha(review)
    assert report['proofs'] == [
        dict(zoom=16, status='matched', raster_sha256=sha(z16)),
        dict(zoom=17, status='matched', raster_sha256=sha(z17)),
    ]
    assert 'the envelope does not approve fine output' in report['scope']
    assert snapshot() == before


def test_swapped_summary_rejects_a_different_valid_raster(inputs, tmp_path, capsys):
    """Equal zoom, tile IDs and counts cannot substitute for the exact raster hash."""
    summary, review, z16, z17 = inputs
    other = _raster(tmp_path / 'other-z16.tif', OTHER_Z16)
    summary.write_text(json.dumps([_row(16, OTHER_Z16), _row(17, Z17)]), encoding='utf-8')
    assert _run(summary, review, other, z17) == 0
    capsys.readouterr()
    assert _run(summary, review, z16, z17) == 1
    out, err = capsys.readouterr()
    assert not out and 'z16 proof bytes do not match summary raster_sha256' in err


def test_reused_digest_refuses_both_zooms_before_reading_proofs(inputs, capsys, monkeypatch):
    """Copying the z16 raster to a second pathname cannot supply a z17 proof."""
    summary, _, z16, z17 = inputs
    z17.write_bytes(z16.read_bytes())
    summary.write_text(json.dumps([_row(16, Z16), _row(17, Z16)]), encoding='utf-8')
    proof_reads = []
    hash_file = receipts.sha256_file

    def record_hash(path):
        if path in (z16, z17):
            proof_reads.append(path)
        return hash_file(path)

    monkeypatch.setattr(receipts, 'sha256_file', record_hash)
    code = _run(*inputs)
    out, err = capsys.readouterr()
    assert (code, out) == (1, '')
    assert 'z16 and z17 must declare distinct raster_sha256 values' in err
    assert not proof_reads


@pytest.mark.parametrize('missing', ['argument', 'file', 'summary_row'])
def test_omitted_zoom_is_incomplete(inputs, capsys, missing):
    """Neither a declared hash nor a supplied path alone can make a zoom matched."""
    summary, review, z16, z17 = inputs
    if missing == 'summary_row':
        summary.write_text(json.dumps([_row(16, Z16)]), encoding='utf-8')
    elif missing == 'file':
        z17 = z17.with_name('missing.tif')
    else:
        z17 = None
    assert _run(summary, review, z16, z17) == 2
    out, err = capsys.readouterr()
    report = json.loads(out)
    assert not err and report['status'] == 'incomplete'
    assert report['envelope_sha256'] == sha(review)
    assert report['proofs'] == [
        dict(zoom=16, status='matched', raster_sha256=sha(z16)),
        dict(zoom=17, status='incomplete', missing=['summary_row' if missing == 'summary_row' else 'artifact']),
    ]


def test_envelope_digest_requires_verified_layers(inputs, capsys):
    """An unchanged envelope file must not hide a changed pinned layer."""
    _, review, _, _ = inputs
    archive = review.parents[2] / package.ARCHIVE
    archive.write_bytes(b'changed layer')
    assert _run(*inputs) == 1
    out, err = capsys.readouterr()
    assert not out and 'layer hash or size changed' in err
