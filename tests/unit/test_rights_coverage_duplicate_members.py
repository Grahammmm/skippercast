"""Ambiguous JSON must be refused at input admission, not resolved last-key-wins."""
import json
from unittest.mock import patch

import pytest

from scripts.coast_diagnostics import rights_coverage as coverage
from tests._support import FIXTURES


@pytest.mark.parametrize(('path', 'raw'), [
    # Last-key-wins can hide the missing source entirely.
    ('recipe.json', r'{"sources": ["missing"], "sources": ["federal"]}'),
    # Decoding escapes must not hide a repeated member in a catalog row.
    ('catalog/sources.json', r'{"sources": [{"id": "missing", "\u0069d": "federal"}]}'),
    # Even ignored metadata in a candidate file must be unambiguous.
    ('catalog/candidates/other.json', r'{"id": "other", "meta": [{"note": 1, "note": 2}]}'),
])
def test_duplicate_member_refused_before_resolving_or_writing(tmp_path, capsys, path, raw):
    root = tmp_path.resolve()
    (root / 'catalog/candidates').mkdir(parents=True)
    row = json.loads((FIXTURES / 'n3_rights_coverage/federal.json').read_text(encoding='utf-8'))
    recipe = root / 'recipe.json'
    recipe.write_text('{"sources": ["federal"]}', encoding='utf-8')
    (root / 'catalog/sources.json').write_text(json.dumps({'sources': [row]}), encoding='utf-8')
    (root / path).write_text(raw, encoding='utf-8')
    output = root / 'new-parent' / 'report'

    with patch.object(coverage.rights_module, 'source_rights', wraps=coverage.rights_module.source_rights) as resolve:
        assert coverage.main(['--repo-root', str(root), '--recipe', str(recipe),
                              '--output-root', str(output)]) == 2
    resolve.assert_not_called()
    stdout = capsys.readouterr().out
    assert stdout.startswith('INPUT_ERROR ')
    assert 'duplicate JSON member' in stdout
    assert not output.parent.exists()
