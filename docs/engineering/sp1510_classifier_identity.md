# Classifier identity v3 (SP-15-v1 / SP1510-CLASSIFIER-IDENTITY)

The classifier version keeps the public grammar `c<algorithm>-<16 lowercase hex>`.
`ALGORITHM_VERSION` is now 3 because the fingerprint representation changed.
Every previous v2 identity intentionally changes. This is not a threshold or
classification/segmentation algorithm change, data migration, or instruction to
reprocess any live records.

## Identity input

SHA-256 hashes UTF-8 compact JSON with sorted keys. Its top-level members are:

- `algorithm`: `ALGORITHM_VERSION`;
- `activity`: the complete raw activity mapping, including auxiliary and unknown
  keys such as `simplify_tolerance_m`;
- `effective`: every `ActivityThresholds` dataclass field except `raw`, discovered
  by dataclass field enumeration, including each `max_open_trip_hours` entry.

Mappings (including read-only mapping proxies) and list/tuple containers are
recursively converted into JSON containers. Object key insertion order at any
level does not change identity. Existing JSON number/string encoding remains
unchanged; this is not a general numerical-equivalence normalization scheme.
The first 16 hexadecimal digest characters follow the version prefix.

This captures effective typed overrides made with `dataclasses.replace` or
public direct construction, even when the raw mapping stays unchanged. The
old implementation could label the same synthetic one-knot trip `drift-anchor`
with a typed drift threshold of 2.0 and `uncertain` at 0.5 while emitting the
same version. Production incidence of typed overrides is unverified.

## Offline acceptance

Run from the clone, using the sibling operator-staged `SOURCE-MANIFEST.json`.
The helper derives paths from its own location, verifies the staging schema,
repo/base identity, and uses staged test/scanner interpreters without fallback.
Each invocation makes a unique directory under the supplied candidate `out`
root. It records stdout and stderr separately, child argv/cwd/runtime/exit,
structured test counts, source hashes and raw-output hashes.

    python3 scripts/accept_sp1510_classifier_identity.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp1510_classifier_identity.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp1510_classifier_identity.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp1510_classifier_identity.py --suite repository --output ../out/author-repository

Baseline is historical evidence on unchanged pinned product code ONLY, before
repair. It executes exactly `test_primary_regression` and `test_healthy_control`.
Success means child exit 1, the specific A1 collision assertion failed, healthy
control passed, and no errors/skips occurred: `BASELINE_GAP_REPRODUCED`, never
repair success. Do not rerun baseline against repaired code or relabel the old
receipt. Focused reuses the identical pair inside its eight-test suite.

A1 checks label-changing effective drift overrides through `classify_trip`.
A2 checks repeats and recursively reordered raw/typed mapping keys.
A3 varies all typed fields individually (each max-open mapping value separately)
and raw auxiliary/new nested keys. A4 pins original labels, tiling, positions,
statistics, basis and geometry of the synthetic stationary trip, and verifies
that the changed label does not change those non-label properties. Additional
checks pin the canonical representation, algorithm bump and Mapping protocol.
Fixtures contain public dataclass-shaped synthetic inputs, no real track.

Regression first executes the original dotted selector
`tests.unit.test_fleet_classify` via a file bootstrap of `unittest` module main,
then executes the unchanged file with pytest so its parametrized function tests
are not silently omitted. Child imports are anchored to this clone and their
paths/hashes verified. No original tests are modified. Repository runs the
unchanged `scripts/check_repository.py` using the staging manifest's
`runtime.credential_scan_python3`, not a system-Python fallback.

Pre-import network/model/process/SQLite guards and candidate-root binding apply
to test children. The complete actual product modules execute; no planner
extracts, fake classifier, or external implementation is imported. The raw-store
module imported by AIS package initialization defines APIs without eager I/O;
its access entrypoints are then denied before test execution. All patches are
scoped/restored (including under ordinary test discovery), and no irreversible
audit hook is installed. These are regression sentinels, not a hostile-code
sandbox. No network connection or real-store operation is used as a control.

Scoped green remains REVIEW REQUIRED. Full repository CI, Node/Python discovery,
survey/GIS accounting, regional/search parity, other privacy/credential checks,
web/client/copy/token checks, typecheck/build, dependency audit and browser/e2e
remain operator-owned and OWED. Python-only scope does not add TypeScript/build
modes here. No source acquisition, publication, live processing, migration,
service/profile change, merge, hold release, or semantic/navigation/fish-presence
acceptance is authorized by this change. Independent review of Sol-authored
material belongs solely to actual Claude Opus 5.5 on `opus-coder-bopus`.
