# Runbook: roll back a regional relief release

**When:** the region's post-deploy `live-check` reports `FAIL` for the release,
or review finds a problem with the released data. Record the region, the bad
release commit and the failure or review finding in the rollback PR.

This rolls back data for one region, not Worker code. For a code regression,
see [Roll back a release](rollback-release.md). While waiting, the browser
hides the affected relief layer on a hash mismatch rather than drawing
unverified relief. The old archives are immutable; no R2 objects are changed
or deleted.

## Prepare and review

1. Start with a clean, full clone checked out at current `main`. Confirm the
   bad release is the last change to this region's catalog pair; the command
   restores the state before that change. Do not rerun it on a rollback branch.
2. From a checkout with the relief tools installed, run:

   ```bash
   python scripts/relief/region.py rollback --region "$REGION" --repo "$CLONE"
   ```

   Replace `REGION` and `CLONE` with the region ID and clone path. The command
   creates and checks out `rollback/<id>-<short HEAD sha>` in the clone; use
   `--branch` to supply a different unused name. It prints the branch, commit
   and the two paths' before/after SHA-256 values (or `removed` for a file it
   removes). On refusal, stop and resolve the reported cause before trying again.
3. Review the printed commit. Only `catalog/relief/<id>.json` and
   `catalog/depth-contours/<id>.geojson` may change. A first release can be
   undone by removing a file with no predecessor. The command does not push;
   follow its printed push step and open one PR into `main` naming the region.
   Merge under standing approval only after independent review and required
   checks pass on the exact PR head. The normal deploy follows the merge.

## Verify after deploy

Check that the deployed revision includes the rollback merge. Update the clone
to merged `main` and use a tools checkout that includes `region.py live-check`.
Set `OUT` to the pipeline output directory, then run:

```bash
python scripts/relief/region.py live-check --region "$REGION" --out "$OUT" --repo "$CLONE"
```

For a restored pointer, require `PASS` and record the resulting `live.json`
under `OUT/<id>/live/<generation>/` on the incident. If the rollback removed
the pointer entirely, `live-check` has no archive to verify: do not expect
`PASS`. Confirm the deployed revision includes the rollback, the old pointer
is no longer served and the relief layer is absent for that region.
