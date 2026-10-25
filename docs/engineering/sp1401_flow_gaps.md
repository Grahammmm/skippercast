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
`scripts/accept_sp1401_flow_gaps.py` (`--suite baseline|focused|regression|repository|typecheck|build|selftest`).

| Row | Mode | Test(s) |
| --- | --- | --- |
| A1 | focused | `A1: no emitted segment crosses a one-pixel gap: east/west, north/south and diagonal cells` (12 fixture cases: east/west and north/south flows with a one-pixel strip on either side of the seed, and four diagonal cases through the centre of a one-pixel cell 1 px ahead of or behind the seed; complete segments are tested by segment/rectangle intersection, and each case is shown to be a real sub-step gap for the unchanged probes); `A1: the gap ends the path at its last supported vertex and leaves the other seed untouched` |
| A2 | focused | `A2: a fully supported constant vector keeps the baseline points, speed, fast flag and direction`; `A2: the seed grid and MAX_PATHS cap are unchanged on a large screen`; `A2: still water and a broad gap the probes already caught keep their baseline results`. Existing broad-gap, ragged-grid and boundary controls in `tests/test_flow.mjs` run unchanged in regression mode. |
| A3 | focused | `A3: each five-pixel segment is sampled a constant bounded number of times at most one pixel apart`; `A3: zero support, short paths and the viewport edge keep their existing results`; `A3: the vector function, its field and masks are not mutated` |
| A4 | baseline, then focused | `primary regression` (the first A1 case against the complete module) and `healthy control` (the identical eastward fixture without the strip keeps the original line and direction). Baseline mode registers only this pair and requires exactly one assertion failure (`ERR_ASSERTION`, no product exception or setup error), one pass, no skips: `BASELINE_GAP_REPRODUCED`. After the product edit the same two tests pass inside focused mode. |
| compatibility | regression | `tests/test_flow.mjs`, unchanged, all 14 tests, no skips |

## Launcher preflight and evidence identity

Before any fixture byte is hashed or any child is launched, every mode of
`scripts/accept_sp1401_flow_gaps.py` requires:

- `SOURCE-MANIFEST.json` `head` to equal the admitted staged base
  `33734f90073a2150eac5a418564ea314c4a591ac` literally, and that commit to be an
  ancestor of HEAD whose `web/map/flow.ts` bytes match the pinned SHA-256. A
  later ancestor with the same primary bytes (for example the A4 test commit)
  is refused. `commits_since_base` is always listed from the admitted base.
- the fixture ancestry `tests`, `tests/fixtures`, `tests/fixtures/sp1401_flow_gaps`
  to be real directories and every entry below it to be a real directory or a
  regular file (lstat only: links, FIFOs and other inputs are refused without
  being followed or opened); the primary, new test, this note and the
  regression files must be regular, non-link files. Staged shared links outside
  this subtree (`.venv`, `node_modules`) are not inspected or changed.
- `tests/fixtures/sp1401_flow_gaps/frozen-spec-SP-14-v1.json`, a verbatim
  portable transcription of the frozen SP-14-v1 item for this card (not a test
  input), to match the SHA-256 pinned in the launcher. Every receipt records
  `specification_file`, `specification_sha256` and the pinned value, so a
  changed specification representation yields a different evidence identity
  and is refused.

`--suite selftest` exercises these refusals on disposable synthetic trees inside
its own run directory: fixture root, intermediate, `tests` and leaf links and a
FIFO leaf are refused (link targets are made unreadable during the checks, so a
followed link would raise), regular synthetic and committed fixture trees pass;
the exact base passes and the first commit after it (a real ancestor with the
pinned primary bytes) is refused; the committed spec passes while a one-byte
change or a link to it is refused, with a distinct hash. Self-test success is a
launcher contract check only.

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
