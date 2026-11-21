"""Destination checks for the local staging path, using a synthetic reviewed release."""
import pytest

from skippercast.relief import stage_transport as stage
from tests.unit.test_relief_stage_transport import assembly, prepare, reviewed  # noqa: F401


@pytest.mark.parametrize('kind', ['file', 'directory', 'dangling-symlink'])
def test_occupied_destination_is_refused_before_approval(reviewed, tmp_path, monkeypatch, kind):
    output = tmp_path / 'stage'
    target = tmp_path / 'missing'
    if kind == 'directory':
        output.mkdir()
        sentinel = output / 'keep'
    else:
        sentinel = output
    if kind == 'dangling-symlink':
        output.symlink_to(target)
    else:
        sentinel.write_bytes(b'keep these bytes')

    # A late-only check would perform queue lookup and could start copying assets.
    def unexpected_approval(*_):
        pytest.fail('occupied destination reached approval lookup')

    def unexpected_stage(**_):
        pytest.fail('occupied destination reached asset staging')

    monkeypatch.setattr(stage, 'TemporaryDirectory', unexpected_stage)
    with pytest.raises(stage.StageError, match='^choose a new stage directory$'):
        prepare(reviewed, output, unexpected_approval)

    if kind == 'dangling-symlink':
        assert output.is_symlink()
        assert output.readlink() == target
        assert not output.exists()
    else:
        assert sentinel.read_bytes() == b'keep these bytes'
        if kind == 'directory':
            assert list(output.iterdir()) == [sentinel]


def test_destination_that_appears_during_copy_is_not_replaced(reviewed, tmp_path, monkeypatch):
    output = tmp_path / 'stage'
    checked = stage._checked

    # A preflight-only check could rename over an empty directory on POSIX.
    def checked_with_arrival(*args, **kwargs):
        checked(*args, **kwargs)
        if not output.exists():
            output.mkdir()

    monkeypatch.setattr(stage, '_checked', checked_with_arrival)
    with pytest.raises(stage.StageError, match='^choose a new stage directory$'):
        prepare(reviewed, output, lambda *_: reviewed.approval)

    assert output.is_dir()
    assert not list(output.iterdir())
    assert not list(tmp_path.glob('.relief-*'))
