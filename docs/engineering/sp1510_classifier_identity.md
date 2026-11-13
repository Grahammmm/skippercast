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

## Tests

`tests/unit/test_sp1510_classifier_identity.py` runs under ordinary pytest and
unittest discovery. `test_primary_regression` and `test_healthy_control` are the
A1 pair: on the unchanged pinned product code before the repair the A1 collision
assertion failed while the healthy control passed.

A1 checks label-changing effective drift overrides through `classify_trip`.
A2 checks repeats and recursively reordered raw/typed mapping keys.
A3 varies all typed fields individually (each max-open mapping value separately)
and raw auxiliary/new nested keys. A4 pins original labels, tiling, positions,
statistics, basis and geometry of the synthetic stationary trip, and verifies
that the changed label does not change those non-label properties. Additional
checks pin the canonical representation, algorithm bump and Mapping protocol.
Fixtures contain public dataclass-shaped synthetic inputs, no real track.

Test-scoped network/model/process/SQLite sentinels are installed in `setUp`
before the product imports. The complete actual product modules execute; no
planner extracts, fake classifier, or external implementation is imported. The
raw-store module imported by AIS package initialization defines APIs without
eager I/O; its access entrypoints are then denied before test execution. All
patches are scoped and restored, and no irreversible audit hook is installed.
These are regression sentinels, not a hostile-code sandbox. No network
connection or real-store operation is used as a control.

Scoped green remains REVIEW REQUIRED. Full repository CI, Node/Python discovery,
survey/GIS accounting, regional/search parity, other privacy/credential checks,
web/client/copy/token checks, typecheck/build, dependency audit and browser/e2e
remain operator-owned and OWED. Python-only scope does not add TypeScript/build
modes here. No source acquisition, publication, live processing, migration,
service/profile change, merge, hold release, or semantic/navigation/fish-presence
acceptance is authorized by this change. Independent review of Sol-authored
material belongs solely to actual Claude Opus 5.5 on `opus-coder-bopus`.
