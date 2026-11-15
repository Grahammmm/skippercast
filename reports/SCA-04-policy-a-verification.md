# SCA-04: policy-A binding finding verification

Checked against skippercast `origin/main` = `351e321dd8c7b3ef82b149d2bb9476fbe337e180` (clone 2026-11-15).

No source or test change; row closed as already fixed before merge.

## Finding

The Codex RETURN on PR #2192 (head `79ac923d`) asked that also-check links be enforced exactly and kept out of blocking sources.

- PR #2192 merged as `853bc93b777e7365fe5ed845260cacca74c286fb`.
- Fix commit: `85ede5f9da03e3381677892be5125759dc3fea00` (parent `27885a23756b550aa7c5a36793ec182ef37bb4eb`). It changes `src/skippercast/pipeline/regulations.py` and `tests/contract/test_rules_policy_a_and_pending_review.py`.

```console
$ git merge-base --is-ancestor 85ede5f9da03e3381677892be5125759dc3fea00 853bc93b777e7365fe5ed845260cacca74c286fb; echo $?
0
```

The fix is an ancestor of the merge commit, so it was fixed BEFORE merge.

## Current code (`src/skippercast/pipeline/regulations.py:78-83`)

`expected_links = also_check - required - set(per_species.get(ident, []))`, then `if links != expected_links or blocking & expected_links: raise ValueError(...)`.

## Tests (positive)

```console
$ python -m pytest -o "pythonpath=. src" -p no:cacheprovider -q tests/contract/test_rules_policy_a_and_pending_review.py tests/contract/test_pipeline_regulations.py
....................                                                     [100%]
20 passed in 0.18s
```

The two rejected-mutation tests are in `tests/contract/test_rules_policy_a_and_pending_review.py` (halibut given `rules-proposals` as a blocking source; salmon given `rules-health`).

## Negative control (scratch checkout, never committed)

Pre-fix `regulations.py` restored with `git checkout 85ede5f9da03e3381677892be5125759dc3fea00^ -- src/skippercast/pipeline/regulations.py`:

```console
FAILED tests/contract/test_rules_policy_a_and_pending_review.py::test_binding_refuses_drift_from_policy_a[<lambda>-Also-check links3]
FAILED tests/contract/test_rules_policy_a_and_pending_review.py::test_binding_refuses_drift_from_policy_a[<lambda>-Also-check links4]
2 failed, 10 passed in 0.09s
```

After `git checkout HEAD -- src/skippercast/pipeline/regulations.py`, `git status --short` printed nothing (clean).

## Conclusion

Both rejected-mutation tests exist and fail without the fix. No new test is needed (it would duplicate coverage).
