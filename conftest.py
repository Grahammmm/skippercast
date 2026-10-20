"""Repository-wide pytest setup, loaded before tests/ and research/tests/ conftests.

pytest imports skippercast from src/ (an editable install or PYTHONPATH=src). Left
alone, that writes src/skippercast/**/__pycache__, which the coastal source guard
(src/skippercast/coastal/_source_bootstrap.py) rightly refuses, so a coastal runner
pointed at a worktree that ran the tests would stop before its first stage. Turn
bytecode writing off here, before any project import, for this process and for the
Python subprocesses tests start (python -I ignores the variable; those tests set
their own flags).
"""
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
