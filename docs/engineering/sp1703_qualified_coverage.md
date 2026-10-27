# SP1703: qualified bottom-view coverage is bound to decoded samples

Spec SP-17-v1, card SP1703-QUALIFIED-COVERAGE.

## What changed

`validate_qualified_scope` (src/skippercast/platform/qualified_scope.py) already
required each qualified bottom view to declare a `coverage_fraction` between 0
and 1, equal in the tile and in the published bottom index, with a correctly
sized `base64-int16-le` raster and nodata sentinel `-32768`. Before this change,
the declared value was never compared with the raster itself. A view whose
samples were all nodata could still claim a coverage of 1.

The validator now decodes each raster once. It counts the signed little-endian
int16 samples that differ from the nodata sentinel and requires the declared
coverage to equal `round(valid / (width * height), 4)`. That is the same value
the producers write (`research/scripts/build_socal_targets.py`
`numeric_view`). On a mismatch, publication fails closed with
`Bottom view coverage differs from its decoded valid samples`.

## What did not change

- The encoding, dimension, nodata, cell-size and tile/index agreement checks
  keep their order and messages. So do the malformed-base64 (`binascii.Error`)
  and wrong-length (`Bottom view raster is incomplete`) refusals.
- Artifact and receipt hashes, source identity, the original-survey holds,
  native depth and resolution qualification, footprint and closure screening,
  and the limited-scope result all run before this check and are unchanged.
- No minimum-coverage policy is added or relaxed. An honest zero claim on an
  all-nodata view still meets the binding. Any positive claim on that view is
  rejected.

## Tests and acceptance

`tests/unit/test_sp1703_qualified_coverage.py` builds wholly synthetic releases
from `tests/fixtures/sp1703_qualified_coverage`, recomputing every hash, and
runs them through the real validator.

- `BaselineTests` holds the frozen pair:
  - `test_primary_regression`: an all-nodata view that claims coverage 1.
  - `test_healthy_control`: the same release with valid samples.
- A1 to A4 cover:
  - matching, rounded, mismatched and zero-coverage claims;
  - multi-target binding;
  - signed little-endian decoding;
  - the refusals that already existed;
  - the source-hold, depth, footprint and integrity checks that still apply.

`scripts/accept_sp1703_qualified_coverage.py` runs four phases offline, each
writing to a new run directory under its `--output`:

- baseline (red/green on the pinned-base module)
- focused
- regression (`tests.integration.test_qualified_scope`)
- repository (`scripts/check_repository.py`)

A pass means REVIEW REQUIRED. It is not full-repository CI, and it is not
publication, survey, legal or navigation acceptance.
