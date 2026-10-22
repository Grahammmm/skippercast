# C3 viewer: mask-aware terrain (2026-10-22)

- Branch: `claude/viewer-mask-aware`, from `claude/update-pr838` (base head `c745581d43b9`).
- Code commit: `ca862e5a5395` (this report is committed on top of it).
- Synthetic fixtures only. No real or private data.

## Problem

C2 writes unsupported pixels as alpha=0, RGB=0. MapLibre decodes RGB only, so RGB=0 becomes
-10000 m. That draws a false cliff at every support edge (PR #845 shows it on real tiles).

## Fix

- New `packages/coast/src/coast3d/mvp-mask.ts`.
- Terrain tiles load through a same-origin `mvpmask://` protocol. It fetches the PNG without
  premultiplying alpha and treats any cell with alpha < 255 as unsupported.
- Unsupported cells take the nearest supported cell's elevation (flat fill), so nothing is
  below the real minimum or above the real maximum, and the output is fully opaque.
- A tile with no supported cell is rejected, so MapLibre treats it as missing.
- Banner and rights panel are unchanged; the note now says no-data cells are filled, not measured.
- Limit: the fill is a display device. It is not data, and it hides the hole's shape in the hillshade.

## Tests (`tests/test_coast_mvp.mjs`)

- Regression: raw RGB decode of an alpha=0 cell gives -10000 m (the old behaviour).
- Masked path: a synthetic tile with holes gives no elevation below the real minimum
  (or above the maximum); supported cells are unchanged; all alpha is 255.
- Partial alpha counts as unsupported; an all-empty tile returns null; wrong size throws.

## Commands and results

| Command | Result |
| --- | --- |
| `pnpm install --frozen-lockfile` | OK |
| `python -m pip install -e ".[test]"` | OK |
| `pnpm check` (tsc, 3 projects) | pass (after fixing one `ImageData` type error) |
| `pnpm build` | pass |
| `node --test tests/test_*.mjs` | 2242 tests, 2241 pass, 0 fail, 1 skipped (not from this change) |
| `python scripts/check_repository.py` | pass |

Not run: the Python suites (no Python files changed) and a browser run of the new protocol
(Chromium capture of the real `OffscreenCanvas` path is untested; unit tests cover the pure mask).

## Should C2 write a sentinel instead of RGB=0?

Yes: RGB=0 is a valid, absurd depth, so consumers that ignore alpha silently get -10000 m.
Options, recommended first:

1. **(Recommended) Keep alpha=0 and also fill RGB with the nearest supported value.**
   Any decoder that ignores alpha still gets plausible edges. Downside: producer needs a
   fill step; alpha must still be honoured to know what is real.
2. **Sentinel RGB (for example 0xFFFFFF, about +6553 m), documented in the contract.**
   Easy to detect and to mask. Downside: still a bogus height if a consumer forgets; needs
   a contract change and a version bump.
3. **Keep RGB=0 and rely on each consumer masking (this PR).**
   No producer change. Downside: every consumer must remember; one miss gives a cliff.
4. **Ship a separate 1-bit support mask tile beside the terrain tile.**
   Cleanest semantics and no overloaded pixels. Downside: two fetches per tile, more files.
