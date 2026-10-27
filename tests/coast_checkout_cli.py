"""Execute a coast script from this exact checkout, without PYTHONPATH injection.

A shared editable installation may point to another worktree. This file sets
its own import path before running the real script in a fresh interpreter.
"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    target = Path(sys.argv[1]).resolve()
    if not target.is_relative_to(ROOT / 'skills') or target.suffix != '.py':
        raise SystemExit('coast CLI target must be a script inside this checkout')
    sys.path[:0] = [str(target.parent), str(ROOT / 'src'), str(ROOT)]
    import skippercast
    if Path(skippercast.__file__).resolve() != ROOT / 'src/skippercast/__init__.py':
        raise SystemExit('coast CLI imported the wrong checkout')
    sys.argv = sys.argv[1:]
    runpy.run_path(str(target), run_name='__main__')
