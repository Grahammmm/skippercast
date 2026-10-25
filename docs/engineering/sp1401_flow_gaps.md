# SP1401: streamlines stop at screen-resolved gaps between integration probes

Specification SP-14-v1, card SP1401-FLOW-GAPS. Scoped engineering note; a
machine-green result here is REVIEW REQUIRED, not semantic, whole-repository or
release acceptance.

## Change

`flowPaths` in `web/map/flow.ts` integrates each half of a streamline in 5 px
midpoint steps (`STEP_PX`). Before this change a proposed step was accepted when
the step's start (`a`), its midpoint direction probe (`b`) and its end were all
supported, so a blocked region narrower than the gap between those probes (for
example a one-pixel null strip at x = 24.5 to 25.5 crossed by a step from x = 24
to x = 29) could be bridged by a drawn segment.

Each proposed step is now sampled along the whole segment at most `SAMPLE_PX`
(1 screen pixel) apart, both ends included, before it is accepted
(`stepSupported`). The step's start is the `a` sample already taken; the end and
the interior points at k/n of the segment (n = ceil(length / SAMPLE_PX)) are
asked next, and the first unsupported sample ends that half of the path exactly
as an unsupported end did before.

Unchanged: integration direction and midpoint rule, seed grid and spacing,
`MAX_PATHS`, `STEP_PX`, `MAX_STEPS`, the more-than-five-points rule, the field
interpolation (`frameField`, `screenVector`), masks, the fast flag and speed
taken from the seed, and all drawing (`drawBase`, `drawDashes`).

## Acceptance map

Tests are in `tests/test_sp1401_flow_gaps.mjs`; synthetic inputs are in
`tests/fixtures/sp1401_flow_gaps/cases.json`. The runner is
`scripts/accept_sp1401_flow_gaps.py` (`--suite baseline|focused|regression|repository|typecheck|build`).

| Row | Mode | Test(s) |
| --- | --- | --- |
| A1 | focused | `A1: no emitted segment crosses a one-pixel gap: east/west, north/south and diagonal cells` (12 fixture cases: east/west and north/south flows with a one-pixel strip on either side of the seed, and four diagonal cases through the centre of a one-pixel cell 1 px ahead of or behind the seed; complete segments are tested by segment/rectangle intersection, and each case is shown to be a real sub-step gap for the unchanged probes); `A1: the gap ends the path at its last supported vertex and leaves the other seed untouched` |
| A2 | focused | `A2: a fully supported constant vector keeps the baseline points, speed, fast flag and direction`; `A2: the seed grid and MAX_PATHS cap are unchanged on a large screen`; `A2: still water and a broad gap the probes already caught keep their baseline results`. Existing broad-gap, ragged-grid and boundary controls in `tests/test_flow.mjs` run unchanged in regression mode. |
| A3 | focused | `A3: each five-pixel segment is sampled a constant bounded number of times at most one pixel apart`; `A3: zero support, short paths and the viewport edge keep their existing results`; `A3: the vector function, its field and masks are not mutated` |
| A4 | baseline, then focused | `primary regression` (the first A1 case against the complete module) and `healthy control` (the identical eastward fixture without the strip keeps the original line and direction). Baseline mode registers only this pair and requires exactly one assertion failure (`ERR_ASSERTION`, no product exception or setup error), one pass, no skips: `BASELINE_GAP_REPRODUCED`. After the product edit the same two tests pass inside focused mode. |
| compatibility | regression | `tests/test_flow.mjs`, unchanged, all 14 tests, no skips |

The expected values for A2 and A3 come from an independent oracle in the test
file: the unchanged midpoint rule written for a constant unit field, not a copy
of `flow.ts`. Six of the ten focused tests (the preservation rows) pass against
the unchanged module as well; the four gap and sampling tests fail there.

## Compatibility deltas

- Sampler calls per accepted 5 px step rise from 3 (`a`, `b`, end) to 7 (`a`,
  `b`, end and four interior points) for unit directions; a terminating step
  costs at most the same. A3 measures this as one constant per segment.
- A path that previously bridged a gap narrower than the probe spacing now ends
  at its last supported vertex; if that leaves five points or fewer the path is
  dropped, as any short path was before.
- New exported constant `SAMPLE_PX = 1`.

## Limitations

- A one-pixel screen-resolution guarantee: a closed blocked region at least one
  pixel across the segment's path is caught. Narrower or half-open regions that
  fall strictly between samples are not; this is not a sub-pixel geometry proof.
- The `ScreenVector` contract is a unit direction. A non-unit vector lengthens
  the step and the sample count with it (still at most 1 px apart); the end of
  a step is inside the screen before any interior point is asked, so the count
  stays bounded by the screen size.
- The synthetic fixtures are screen samplers only: no map, raster, terrain,
  navigation, safe-water or fish-presence conclusion follows.
- Full-repository discovery, the CI matrix and browser checks remain owed to
  the operator and CI at the exact head (full discovery = operator-run).
