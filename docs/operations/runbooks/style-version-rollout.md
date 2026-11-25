# Runbook: cut a new map style version and roll it out region by region

**When:** the map owner has approved a new look, either a new nearshore relief
version (`style/nearshore-v<X.Y.Z>.json`) or a new all-layers version
(`style/layers-v<X.Y.Z>.json`). Follow it from the first file you add to a
revert, if one is needed. It changes no data, publishes nothing and runs no
region build: the pipeline runs and their R8 reviews stay with the people who
own them, and every hold on a region stays in force.

The rules behind it are in [`style/README.md`](../../../style/README.md):

- A released version file and its raw-byte SHA-256 in `style/index.json` are
  **immutable**. A new look is a new file and a new index entry.
- `index.json` `default` (nearshore) and `layers_default` (all layers) are the
  only switches for the whole site.
- Only the nearshore style can be **pinned per region**, through the optional
  `style` member of `regions/<id>/render.json`. The all-layers style has no pin.

| | Nearshore relief style | All-layers style |
| --- | --- | --- |
| Files | `nearshore-v<X.Y.Z>.json` | `layers-v<X.Y.Z>.json`, plus `stacking-v<X.Y.Z>.json` if it changed |
| Switch | `default`, or a per-region `style` pin in `render.json` | `layers_default` only |
| Enters relief rebuilds | Yes: the baked, contours and habitat digests | No |
| Rebuild preview | `rebuild_plan.py` | none needed; the generator check is the gate |
| Mixed versions on one map | Yes (each region's pointer carries its own look) | No |
| Rollback | revert the data PR(s) first, then the style PR | revert the one PR that moved `layers_default` |

## Before you start

1. Work from a clean, up-to-date clone of `main` on a new branch, with the
   checkout's own package installed (`python -m pip install -e ".[test]"`). The
   previews below read `style/` and `regions/` through the installed
   `skippercast` package, so an interpreter that imports another checkout
   previews that checkout, not yours.
2. Set the shell variables used below. `OUT` is the relief output root that holds
   the region receipts (`$OUT/<region>/stages/`). `OLD` is the current default.

   ```sh
   export OLD=nearshore-v1.0.0 NEW=nearshore-v1.1.0 REGION=<region id> OUT=<relief output root>
   ```

3. Confirm the starting point is green: `python scripts/style/gen_style.py --check`
   must print `... style tokens and projections match`.

## Part 1: a nearshore version

### 1. Cut the version (one PR, default unchanged)

1. Copy the kit's `style-guide/style-tokens.json` byte-for-byte to
   `style/$NEW.json`. Never edit it afterwards, and never edit an existing
   version file. Only derived tokens go in the repo; the kit archive and its
   fixtures stay private. Note the file's SHA-256:

   ```sh
   sha256sum style/$NEW.json
   ```

2. If the new file has keys that `style/groups.json` does not yet classify, add
   them there (the longest matching prefix wins; there is no default group).
   Reassigning an existing key is a new version, never an edit.
3. In `style/index.json`, add `versions.<NEW>` with `file`, `sha256`,
   `kit_zip_sha256` and `"status": "rolling"`. **Leave `default` alone.** Do not
   type the four `digests`; the generator writes them.
4. Generate, then check:

   ```sh
   python scripts/style/gen_style.py
   python scripts/style/gen_style.py --check
   ```

   Before the first command, `--check` fails with `index digests disagree`;
   that is expected. After it, `--check` prints
   `<default> + <layers default>: style tokens and projections match`. The
   generator rewrites `style/index.json` (digests), `web/tokens.css`,
   `web/map/nearshore-style.gen.ts` and `packages/coast/src/palette.ts` because
   a `rolling` version adds its look to the generated tables. Commit the inputs
   and the regenerated files together; never hand-edit a generated block.
5. Classify the change, which decides how much work follows:

   ```sh
   python scripts/relief/style_diff.py $OLD $NEW
   ```

   `paint_only=true` means only the paint group changed: that change alone does
   not give a render stage a new generation. Unchanged digests do not waive
   applicable R8 review, a reviewed data PR, or any release hold for the regional
   rollout below. If `groups_changed` includes `baked`, `contours`, or `habitat`,
   the stages that read those groups must rebuild before regional review.

### 2. Preview the rebuild, region by region

`rebuild_plan.py` is read-only. It compares each region's receipts with the style
you propose and prints one row per stage (`reuse` or `rebuild`, with reasons
such as `style:baked`, `style:contours`, `style:habitat` or `upstream:<stage>`)
and a summary line `regions=<n> rebuild_heavy=<m>`, where heavy means a
`mosaic` or `tiles` rebuild. It runs no stage and does not verify outputs. A
region with no receipts shows `missing`, so point `--out` at the real output
root.

```sh
# If NEW became the default (regions without a pin follow it):
python scripts/relief/rebuild_plan.py --out "$OUT" --style-default $NEW $REGION
# If only one region is pinned to NEW (the other regions keep their current style):
python scripts/relief/rebuild_plan.py --out "$OUT" --style-default $NEW --style-pin $REGION=$NEW $REGION
# One document for a report; list every region you want to see:
python scripts/relief/rebuild_plan.py --out "$OUT" --json --style-default $NEW $REGION
# The preview windows to capture before the pack is reviewed:
python scripts/relief/style_preview_plan.py $NEW $REGION
```

- A proposed pin overrides the region's saved `render.json` pin for this run only,
  and a saved pin hides a proposed default for that region.
- Exit 2 with `unavailable render style: <id>` means the version is not in the
  index or is `retired`. Exit 2 with `--style-pin region not in report` means the
  region was not listed on the command line.
- Share the output in the PR. A `rebuild_heavy` count above zero is the wall
  time the owner of the pipeline has to schedule; do not start the runs yourself.

### 3. Pin one region first (second PR)

1. Edit `regions/$REGION/render.json` and set only its `style` member.
   Replace `<NEW>` below with the exact indexed version selected as `$NEW` in
   “Before you start”. JSON does not expand shell variables; do not paste the
   placeholder or a literal `$NEW` into the file.

   ```json
   "style": "<NEW>"
   ```

   The file is validated against `schemas/sc-render-v1.schema.json`: unknown keys
   are rejected, and `style` must match `^[a-z0-9.-]{1,64}$`.
   If the region has **no** `render.json` yet, create one with `schema`
   (`sc-render/1`), `region`, `style`, `previews` and `piers`. An empty
   `previews` list replaces the default preview windows, so copy the windows that
   `style_preview_plan.py` printed for the region instead.
2. Check that the region now resolves to the pin, with nothing run:

   ```sh
   python scripts/relief/run_region.py $REGION --dry-run
   python scripts/relief/rebuild_plan.py --out "$OUT" $REGION
   python scripts/relief/style_preview_plan.py $NEW $REGION
   ```

   The dry run prints `tiles style: <id>; B=<baked digest>` (it must name `$NEW`)
   and `dry run: ... nothing was run and nothing was written`. `style_preview_plan.py`
   reports the region as `unchanged` once it is on `$NEW`.
3. Merge on required CI and independent review. The pipeline owner then runs the
   region under the usual guards, reviews the pack and the R8 packet, and ships
   the region's data PR. That data PR is the live rollout for the region. Wait
   for its review and deploy before moving on; take other regions one at a time
   the same way.

### 4. Move the default (third PR)

1. Only when every region you pinned is approved: in `style/index.json` change
   `default` to `$NEW` and nothing else. Regions with a pin keep it; regions
   without one now follow the new default and rebuild on their next run.
2. Regenerate and check, and re-run the rebuild preview for **all** regions you
   expect to change (the `--style-default` preview from step 2 without a pin):

   ```sh
   python scripts/style/gen_style.py
   python scripts/style/gen_style.py --check
   python scripts/relief/rebuild_plan.py --out "$OUT" --style-default $NEW $REGION
   ```

3. Merge on required CI and independent review. The normal deploy follows. The
   new default's colours and numbers reach the web map at once; each region's own
   depth colours still come from its pointer's look, so regions on the old look
   keep their chips and 3D colours.
4. Once every region follows `$NEW` and no committed pointer or its `previous`
   names the old look, you may flip `$NEW` from `rolling` to `active` and retire
   the old version in `index.json`. `gen_style.py --check` refuses to retire or
   drop a look that a committed `catalog/relief/*.json` pointer (or its
   `previous`) still names. Remove the pins from `render.json` only in a
   separate PR once they equal the default.

## Part 2: an all-layers version

There is no pin, no per-region data PR and no rebuild: layers files are paint for
the web only and never enter a relief generation key. `rebuild_plan.py` has
nothing to say about them. The generator reads only `layers_default`, so add the
version and switch the default in one PR.

1. Copy the kit's `layer-tokens.json` byte-for-byte to `style/layers-v<X.Y.Z>.json`
   and, if the kit's `stacking.json` changed, `style/stacking-v<X.Y.Z>.json`.
   The file's `base_tokens.version` must equal the version of the nearshore file
   you pin as `base`.
2. In `style/index.json` add `layers.<id>` with `file`, `sha256`, `stacking_file`,
   `stacking_sha256`, `base` (an indexed nearshore version), `kit_zip_sha256`,
   `fragment` (`generated/maplibre-layers-v<X.Y.Z>.json`),
   `fragment_canonical_sha256` (the kit's own fragment digest, from the private
   kit parity run on AgentOrange, `scripts/style/kit_layers_parity.py`) and
   `"status": "rolling"`. Set `layers_default` to the new id.
3. Generate and check:

   ```sh
   python scripts/style/gen_style.py
   python scripts/style/gen_style.py --check
   ```

   The first command writes the `--skl-*` CSS block, `web/map/layers-style.gen.ts`
   and the MapLibre fragment. A wrong `fragment_canonical_sha256` fails with
   `fragment canonical sha256 mismatch (got <digest>)`; the fix is a correct kit
   digest, not copying the digest the generator printed.
4. Merge on required CI and independent review; the normal deploy follows. The
   whole site uses the new layers look at once. Mixed layers versions are not
   supported.

## Rollback

| What went live | Revert | Result |
| --- | --- | --- |
| Only the version-cut PR (default unchanged) | that PR, only after resolving every dependency listed below | the new file and entry leave without breaking a dependent region or layers version |
| A region pin, no data PR yet | the pin PR | the region resolves to the default; its generations are the earlier ones again |
| A region's data PR was merged | that region's data PR (then the pin PR if the pin should go too) | the prior pointer returns byte-identical with its own look |
| The nearshore default was moved | the default PR | the old default and its generated files return; the new version stays in the index, so pointers that name its look stay valid |
| A layers default was moved | that one PR | the old layers look returns site-wide |

Reverting is a normal PR: no force-push, and the old archives are immutable.

```sh
git switch -c rollback/style-$NEW origin/main
git revert -m 1 <merge commit of the PR to undo>
python scripts/style/gen_style.py --check
```

(Drop `-m 1` if the PR was squash-merged: `git revert <commit>`.) Open one PR,
merge on required CI and independent review, and let the normal deploy follow.

- **Order matters for the nearshore style.** Reverting a style PR never changes
  what a region's live pointer says. To take a region back, revert its data PR as
  in [roll back a regional relief release](relief-rollback.md)
  (`python scripts/relief/region.py rollback --region $REGION --repo <clean clone>`).
  Before removing the version, revert or migrate every dependent reference in
  reviewed PRs: the nearshore default if it moved, any committed pointer or its
  `previous`, any pin in `regions/<id>/render.json`, and any `layers.<id>.base`
  in `style/index.json`. Roll back the dependent layers version or move to a
  replacement whose base and tokens agree; do not edit an immutable version.
  Confirm these references are gone and run `gen_style.py --check` on the
  proposed revert before asking for review. Keep all existing release holds.
- **Local output.** After a style revert, the earlier generations are current
  again, but the tiles output sits at a fixed path, so receipts cannot restore it
  in place: the next run rebuilds from the cached mosaic. Preview it with
  `python scripts/relief/rebuild_plan.py --out "$OUT" $REGION` from the reverted
  checkout. That costs wall time, not hand work.
- **Layers.** There is nothing to rebuild and no data to restore: revert the PR
  that moved `layers_default` and run `gen_style.py --check`. Do not hand-edit
  `style/index.json` to point back, and never edit or delete a version file.

## Checks and limits

- Every command above is a read-only preview, a `--check`, a `--dry-run`, or a
  step whose result `gen_style.py --check` verifies. If an option here ever
  disagrees with a script, the script's `--help` is current and this page is the
  one to fix.
- The nearshore parity run against the private kit
  (`scripts/style/kit_parity.py`) and the layers parity run
  (`scripts/style/kit_layers_parity.py`) run on AgentOrange only; the kit is not
  in the repository.
- This runbook never starts a region build. `run_region.py` is attended and
  guarded; use it only with `--dry-run` here.
