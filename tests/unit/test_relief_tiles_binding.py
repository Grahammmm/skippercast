"""The tiles stage's receipt digest must cover every file that decides the archive bytes."""
from skippercast.relief import receipts, tiles
from tests._support import ROOT


def test_tiles_digest_covers_the_pmtiles_writer(tmp_path):
    # Contract: build_bathy_tiles.py writes relief.pmtiles through skippercast.relief.pmtiles_v3.
    # Bug caught: a writer-only edit leaves the stage digest unchanged, so the receipt cache
    # reuses an archive made by the old writer instead of rebuilding it.
    files = receipts.module_code_files(tiles)
    labels = [label for label, _ in files]
    assert 'skippercast.relief.pmtiles_v3' in labels
    writer = dict(files)['skippercast.relief.pmtiles_v3']
    assert writer == ROOT / 'src' / 'skippercast' / 'relief' / 'pmtiles_v3.py'
    edited = tmp_path / 'pmtiles_v3.py'
    edited.write_bytes(writer.read_bytes() + b'\n# writer-only change\n')
    changed = [(label, edited if label == 'skippercast.relief.pmtiles_v3' else path) for label, path in files]
    assert receipts.stage_digest(changed) != receipts.stage_digest(files)
