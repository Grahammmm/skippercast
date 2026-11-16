# AUDINV-FIX-057 missing-reviewer regression (CANDIDATE ONLY)

Regression-only package for the installed `~/agent-work/t08a/fresh_admission.py`
nested helper `supersedes(n)` (lines 227-228, script sha256 `220027359d9b...ef6cf`).
It is not an installed replacement and edits no installed admission file.

- Checked finding (VERIFY-1): the installed helper already uses
  `expired[n].get('reviewer_id')`; `valid_until` stays a required `expired[n]['valid_until']`.
  The missing regression was not found in the repo, so this package adds it.
- `sources/supersedes.py` is the exact two-line helper snapshot (sha256 in `BASES.json`).
  Tests locate it by AST, compile only that definition, and inject synthetic
  PRIOR/expired/sha/Path. The installed script is never imported or run.
- Negative control: an AST rewrite of `.get('reviewer_id')` to `['reviewer_id']` raises KeyError.
- Observed behaviour note: an unknown name with no prior file fails with FileNotFoundError
  (the prior-document hash is evaluated first); a name with a prior file but no expired entry raises KeyError.
- All fixtures are synthetic, created under pytest `tmp_path`.
- Not collected by CI (`workspace/candidates` is outside testpaths); run explicitly:

```
python3 -m pytest -q workspace/candidates/AUDINV-FIX-057/tests
```

Result on builder run (repo venv python): `9 passed`.
