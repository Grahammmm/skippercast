"""Exercise the Central request CLI against the binder parser, not its writer."""

from hashlib import sha256
import json

import pytest

from scripts.relief import central_census_bind_request as request
from skippercast.relief import census_bind


REGION = 'big-sur-coast'
OTHER_REGION = 'cambria-san-simeon'
# Preserve the wire bytes (including CRLF); the inventory row is not an input path.
DATA = b'{\r\n "summary": {"region": "big-sur-coast"}, "files": [{"path": "unopened.tif"}]\r\n}\r\n'
SHA = sha256(DATA).hexdigest()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root = tmp_path.resolve() / 'scratch'
    root.mkdir()
    source = root / 'reviewed census.json'
    source.write_bytes(DATA)
    pin = root / 'accepted.json'
    pin.write_text(json.dumps({'region': REGION, 'sha256': SHA}))
    out = root / 'disposable out'

    def forbidden(*args, **kwargs):
        pytest.fail('request generation must never call the binder or writer')

    monkeypatch.setattr(census_bind, 'bind', forbidden)
    monkeypatch.setattr(census_bind, '_write_atomic', forbidden)
    return source, pin, out


def cli(inputs, region=REGION):
    source, pin, out = inputs
    return ['--region', region, '--scratch', str(source.parent), '--census', str(source),
            '--accepted-pin', str(pin), '--out', str(out)]


def test_argv_round_trips_through_real_binder_parser(inputs, capsys, monkeypatch):
    """A renamed flag, split space-bearing path or rewritten census breaks the handoff."""
    source, pin, out = inputs
    pin_bytes = pin.read_bytes()
    assert request.main(cli(inputs)) == 0
    stdout, stderr = capsys.readouterr()
    assert stderr == ''
    argv = json.loads(stdout)
    assert argv == ['--region', REGION, '--out', str(out), '--from', str(source), '--sha256', SHA]

    calls = []
    monkeypatch.setattr(census_bind, 'bind',
                        lambda region, path, sha: calls.append((region.id, region.out_root, path, sha)))
    assert census_bind.main(argv) == 0
    assert calls == [(REGION, out, str(source), SHA)]
    assert source.read_bytes() == DATA and pin.read_bytes() == pin_bytes
    assert set(out.parent.iterdir()) == {source, pin}


@pytest.mark.parametrize('case, diagnostic', [
    ('census-region', 'census region mismatch'),  # matching pin cannot mask a different census region
    ('pin-region', 'accepted pin region mismatch'),  # correct bytes cannot be borrowed from another pin
    ('bytes', 'source SHA-256 mismatch'),  # same pathname/JSON meaning cannot stand in for matching bytes
    ('census-shape', 'census requires a files list'),  # region and digest alone do not make a census
    ('pin-digest', '64-digit hexadecimal SHA-256'),  # a bad pin cannot fall back to a freshly computed digest
    ('duplicate-pin', 'accepted pin has duplicate fields'),  # last-value-wins cannot turn conflict into acceptance
    ('missing-pin', 'separate accepted pin'),  # a reviewed-looking document cannot serve as its own approval
])
def test_refusals_do_not_emit_argv(inputs, capsys, case, diagnostic):
    source, pin, out = inputs
    data, region = DATA, REGION
    if case == 'census-region':
        data = DATA.replace(REGION.encode(), OTHER_REGION.encode())
    elif case == 'census-shape':
        data = DATA.replace(b'"path"', b'"name"')
    elif case == 'pin-region':
        region = OTHER_REGION
    digest = 'not a digest' if case == 'pin-digest' else sha256(data).hexdigest()
    source.write_bytes(data + (b' ' if case == 'bytes' else b''))
    pin_text = json.dumps({'region': region, 'sha256': digest})
    if case == 'missing-pin':
        pin.unlink()
    else:
        pin.write_text('{"region":"decoy",' + pin_text[1:] if case == 'duplicate-pin' else pin_text)

    assert request.main(cli(inputs)) == 1
    stdout, stderr = capsys.readouterr()
    assert stdout == '' and diagnostic in stderr
    assert not out.exists()


def test_out_must_be_explicit(inputs, capsys):
    """A missing OUT must not pick up a pipeline default or emit a partial request."""
    with pytest.raises(SystemExit) as exc:
        request.main(cli(inputs)[:-2])
    assert exc.value.code == 2
    stdout, stderr = capsys.readouterr()
    assert stdout == '' and '--out' in stderr


def test_matching_non_central_pair_is_refused(inputs, capsys):
    """An exact matching region/digest pair is insufficient outside the Central roster."""
    source, pin, _ = inputs
    region = 'synthetic-coast'
    data = DATA.replace(REGION.encode(), region.encode())
    source.write_bytes(data)
    pin.write_text(json.dumps({'region': region, 'sha256': sha256(data).hexdigest()}))
    with pytest.raises(SystemExit) as exc:
        request.main(cli(inputs, region=region))
    assert exc.value.code == 2
    assert capsys.readouterr().out == ''


def test_source_is_not_substituted_by_basename(inputs, capsys):
    """An in-scratch census with the same filename cannot stand in for an outside input."""
    source, _, _ = inputs
    outside = source.parent.parent / source.name
    outside.write_bytes(DATA)
    args = cli(inputs)
    args[args.index('--census') + 1] = str(outside)
    assert request.main(args) == 1
    stdout, stderr = capsys.readouterr()
    assert stdout == '' and 'inside --scratch' in stderr


@pytest.mark.parametrize('case', ['outside', 'existing', 'symlink'])
def test_out_must_stay_fresh_and_scratch_bound(inputs, capsys, case):
    """Do not issue a writer request for an outside, occupied or redirected destination."""
    source, pin, out = inputs
    outside = out.parent.parent / out.name
    if case == 'outside':
        out = outside
    elif case == 'existing':
        out.mkdir()
    else:
        out.symlink_to(outside, target_is_directory=True)
    assert request.main(cli((source, pin, out))) == 1
    assert capsys.readouterr().out == ''
    assert not outside.exists()
