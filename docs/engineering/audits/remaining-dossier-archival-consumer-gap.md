# OLD-07 — remaining dossier archival / consumer gap

## Disposition and exact scope

**HOLD — NO NEW BUILD ADMITTED.** A concrete remaining path exists, but the recorded per-card inventory, external-consumer closure and archival custody are UNKNOWN. This report completes OLD-07; it does not request an owner response as a condition of completion or authorize another cleanup build.

Tracked-source snapshot **`3f699e39554f88304000b004549289c231739446`** (fresh `origin/main`, before this report); evidence collected 2026-11-16 UTC. Every repository observation below is at that snapshot, not a claim about later main. No synthetic observations populate the inventory.

Concrete dossier: `docs/engineering/sp1602_report_unknown_counts.md` (14 lines), SHA256 `1b9f5d7397cdb34d18a088e39dfaf22503471b56f0aee64b917cd70fe77c16d2`.

Provenance: admitted inventory OLD-07, operator-local `reports/audit-inventory/INVENTORY.tsv:357` as quoted in `reports/oc-specs/AUDINV-OLD-07.md:16–23`; G's 2026-11-15 approval retains retire/delete and signing holds. Operator-local locators are relative to the admitted operator work root, not repository files. No private absolute host paths are included.

## Recorded inventory joined to this snapshot

| Evidence | Recorded meaning | Snapshot join / limitation |
| --- | --- | --- |
| `reports/audit/skippercast-AUDIT.md:115` | 62 `sp*.md` / `sc*.md` per-card dossiers; proposed `docs/archive/engineering-notes/` | Aggregate historical claim, not an enumerated custody ledger. |
| `reports/audit/PROPOSED-PLAN-2026-10-31.md:48`, item 6 | Archive the 62 dossiers; preserve unique assertions first | Proposal, not an archival receipt or release authority. |
| `reports/audit/VERIFY-2026-10-31.md:30,52–54` | Dossiers existed; unused/safe-deletion classification NOT CONFIRMED | External/manual consumers and assertion equivalence were not exhaustively proved. |
| OLD-07 recorded row / spec:18,29 | #2188/#2194/#2197 merged; complete archival not independently verified; SP1602 survives | Current source agrees for SP1602; complete per-card join remains UNKNOWN. |
| Current task attachments | None supplied (`kanban_attachments`: `attachments: []`) | No supplied per-card path → destination/hash/history/custodian ledger. |
| Snapshot candidate-name inventory below | 16 direct-child matching names | Filename candidates only: not 16 semantically adjudicated dossiers, and not a reconciliation of the historical 62. |
| Concrete SP1602 join | Card label SP1602 → exact tracked dossier and ordinary test/fixture | Archive destination, archived hash, transfer history, custody receipt and external-user signoff UNKNOWN. |

The three operator-local source files above were hashed read-only: audit `309927d4eeca88cf35fa5aabadbf8c83da44a434b0f8e35f8aa5d016ffedd641`; plan `15e2c3872312239efea35d70c40c75bd58b230544425abaf939f316b26e07859`; verification `bfbf05b5c3ca0c553f40ddf07f255a1c3d388425eda3a28f4984c54f2714422b`.

Bounded command: `git ls-files -- 'docs/engineering/sp*.md' 'docs/engineering/sc*.md' 'docs/archive/engineering-notes/*'`; cwd repository root, exit 0, stderr empty; full stdout:

```text
docs/engineering/sc32_bridge_bounds.md
docs/engineering/sc34_terrain_json.md
docs/engineering/sc38_prefetch_version.md
docs/engineering/sc_cache_clock.md
docs/engineering/sc_catalog_rows.md
docs/engineering/sc_metadata_object.md
docs/engineering/sc_png_dtype.md
docs/engineering/sc_recipe_offline.md
docs/engineering/sc_rights_delta.md
docs/engineering/sc_sample_audit.md
docs/engineering/sc_schema_closure.md
docs/engineering/sc_segment_delta.md
docs/engineering/sp1301_event_segment.md
docs/engineering/sp1510_classifier_identity.md
docs/engineering/sp1602_report_unknown_counts.md
docs/engineering/sp1603_fleet_identity_diagnostic.md
```

No tracked entry in the proposed archive prefix is returned. This does not prove no archive exists elsewhere. Topic docs and ADRs outside this name filter are not automatically dossiers. The old 62 and current 16 have different dates and unjoined membership; their difference is NOT a count of archived files.

## Static, dynamic, documentation and card consumers

Bounded stem search: `git grep -l -F 'sp1602_report_unknown_counts' HEAD -- . ':(exclude)docs/engineering/sp1602_report_unknown_counts.md' ':(exclude)tests/test_sp1602_report_unknown_counts.mjs'`; cwd repository root at pinned HEAD, exit 0, stderr empty; full stdout:

```text
HEAD:docs/engineering/subsystem-retirement.manifest.json
```

Exact dossier-path search: `git grep -l -F docs/engineering/sp1602_report_unknown_counts.md 3f699e39554f88304000b004549289c231739446 -- . ':(exclude)docs/engineering/sp1602_report_unknown_counts.md'`; cwd repository root, exit 1, stdout/stderr empty. **No literal hit is not consumer absence.**

| Consumer class | Concrete evidence / retained owner | Meaning and limit |
| --- | --- | --- |
| Static metadata | `docs/engineering/subsystem-retirement.manifest.json:8`; SHA256 `e91557309336e99e94baeb530dabdb83809225c603b198111bc1ff9c263d047c` | Stem hit names test/fixture inputs, not the dossier path. Its `retain-product` owner covers the dossier through `docs/engineering/`, destination `SkipperCast product`; NOT an archive destination. |
| Frozen dynamic prefix matching | `tests/unit/test_subsystem_retirement_manifest.py:42–60,101–124,198–208` | Reads manifest, enumerates frozen tree and resolves prefixes. Frozen source is `351e321dd8c7b3ef82b149d2bb9476fbe337e180`; status `CANDIDATE ONLY; UNINSTALLED; REVIEW REQUIRED`, applied false. Not a byte-consuming SP1602-doc loader or live retirement proof. |
| Generic Markdown discovery | `scripts/check_repository.py:15,157–186` | `ROOT.rglob('*')` reads non-ignored text and checks Markdown links. The SP1602 note participates without a literal caller naming it. This is a real generic consumer, not proof of application dependence. |
| Test discovery | `package.json:11`; `.github/workflows/ci.yml:416–419` | `tests/test_*.mjs` discovers the ordinary SP1602 suite. It reads the counts fixture and imports production rendering, not this Markdown dossier. |
| Documented/manual use | SP1602 note:3–14 | Contract and direct commands for focused suite and `tests/test_advisor_pages.mjs`; warns historical expected-red receipts are not recreated. Human reference remains plausible even without inbound links. |
| Current card / historical consumers | This OLD-07 brief and spec:29,39 explicitly name SP1602 | Confirmed external documentation consumer; other card/manual users UNKNOWN. No global card-history or external-user census was supplied or inferred. |
| Navigation / topic boundary | `docs/README.md:94–100` | Documents a general archive workflow. It neither supplies the per-card inventory nor authorizes moving these files. ADRs and topic docs remain outside the proposed dossier set. |

Bounded dynamic-consumer probe: `git grep -n -E 'ROOT.rglob|path.suffix|path.read_text|MANIFEST =|startswith\(prefix' HEAD -- scripts/check_repository.py tests/unit/test_subsystem_retirement_manifest.py`; cwd repository root at pinned HEAD, exit 0, stderr empty; full stdout:

```text
HEAD:scripts/check_repository.py:157:    for path in sorted(ROOT.rglob("*")):
HEAD:scripts/check_repository.py:163:        if path.name in {"state.json", "config.json"} or path.suffix in {".pem", ".key"}:
HEAD:scripts/check_repository.py:166:            text = path.read_text(encoding="utf-8")
HEAD:scripts/check_repository.py:179:        if path.suffix == ".md":
HEAD:tests/unit/test_subsystem_retirement_manifest.py:13:MANIFEST = ROOT / 'docs/engineering/subsystem-retirement.manifest.json'
HEAD:tests/unit/test_subsystem_retirement_manifest.py:53:            matches = [p for p in tracked if p.startswith(prefix)] if prefix.endswith('/') else [p for p in tracked if p == prefix]
```

Loader/discovery implementation was inspected read-only, not executed as an unrestricted experiment. This bounded lexical/source inspection is not an exhaustive dynamic call graph. No claim that all glob/generated-path/manual consumers are absent is made.

## Unique assertions and preservation evidence

Retained test `tests/test_sp1602_report_unknown_counts.mjs`, SHA256 `12bebfafd57273ce96587b77ff1e0654de99576ebc3f71c869e0fa60a4d0b270`; fixture `tests/fixtures/sp1602_report_unknown_counts/counts.json`, SHA256 `71b9f162cce918897e46c675800df97cbc533f2ea7c280675a64252948c2ca5e`.

| Contract / unique evidence | Retained assertion owner | Preservation status |
| --- | --- | --- |
| Unknown is not measured zero | SP1602 test:12–18,22–25 | Null/null omitted; explicit zero visible; first three subtests passed. |
| Stable measured order, empty input, release-only/mixed formatting, producer parsing | SP1602 test:21–33 and fixture | Direct ordinary-test assertions retained; A1–A4 passed. |
| HTML escaping at actual report-table boundary | SP1602 test:36–44; `server/advisor/pages/data.ts:65` | Assertions retained, but A5 failed importing dependency before they ran. NOT verified by passing A1–A4. |
| Private-boat nondisclosure | SP1602 test:45–49; `data.ts:64` | Requires anonymous fallback and absence of private label; not reached in this run. No privacy gate changed. |
| Missing/non-finite values stay null | Dossier:5; `server/advisor/pages/render.ts:232–238` | Source implements finite check; selected focused suite does not explicitly assert non-finite normalization. Complete test-equivalence evidence UNKNOWN, not a proved production bug or a new test-build admission. |
| Wider advisor regression | Dossier:11; `tests/test_advisor_pages.mjs` | Existing suite retained, not run here; no equivalence claim based solely on its name. |
| Historical expected-red baseline and receipt integrity | Dossier:14; retired launcher's baseline/TAP and source-manifest checks in history | Ordinary focused pass cannot reproduce historical semantic red/control-green or old raw receipts. Receipt location, hashes and custody UNKNOWN. Do not recreate the retired launcher. |

## Already-completed work and archival gap

#2188 merge `199efc3e4c3271b0a42c0b4e2b5f310e74ee10b4`, #2194 merge `09d3b8f5c6fdd519a5cedb60f87c3a43e8f68040`, and #2197 merge `472bff73d14989e32ad33cd093c6b6ffaff1b2bb` are each ancestors of the pinned snapshot (`git merge-base --is-ancestor <exact merge> HEAD`: exit 0, stdout/stderr empty, three separate calls). Their harness deletions are merged and OUT OF SCOPE.

`git ls-files -- docs/archive/engineering-notes docs/engineering/sp1602_report_unknown_counts.md scripts/accept_sp1602_report_unknown_counts.py research/scripts/accept_sp1602_report_unknown_counts.py`: cwd repository root, exit 0, stderr empty; full stdout:

```text
docs/engineering/sp1602_report_unknown_counts.md
```

`git log --format='%H %s' -- docs/engineering/sp1602_report_unknown_counts.md scripts/accept_sp1602_report_unknown_counts.py`: cwd repository root at pinned HEAD, exit 0, stderr empty; full stdout:

```text
4ec89ea3d3d3a62817399bbcd7dc13150710d3ca Point SP1602 note at direct regression commands
e5c4d2ba68aed17b255c76fdfa39201930ce59b5 Retire redundant SP1602 count-display acceptance launcher
7a82966f3e725dcf9be3d2628b4ec73de25b396e Strengthen unknown-count acceptance coverage
9b0734fa4f3c2b47fbdb6109914cb0eb87597709 Omit unmeasured catch counts from advisor text
```

Historical launcher was read only with `git show e5c4d2ba68aed17b255c76fdfa39201930ce59b5^:scripts/accept_sp1602_report_unknown_counts.py`, never run or restored. It checked exact expected-red text, TAP counts/no skip/cancel/todo, four focused tests and generated hashed receipts. This auxiliary historical observation is not a second current-source inventory snapshot. Git history preserves code, not archival custody or the old generated receipts.

Missing proof goes to the existing SkipperCast documentation/archive custodian and original SP1602 card/receipt custodian (personal identity not supplied): enumerate the historical per-card set; reconcile each current/deleted/moved path; bind destination and bytes to hashes and history; identify retained raw baseline receipts and custody; record external/manual/card consumers and assertion-owner equivalence. These are prerequisite facts for any separately admitted later proposal, NOT new tasks, deadlines or permissions. No deletion/archive release is inferred from administrative classification, merged harness work or machine-valid output.

## Observed adjacent test receipt (incomplete, not retirement clearance)

Command (operator-home prefix normalized to `~`): `~/agent-work/bin/memcap -- node --test tests/test_sp1602_report_unknown_counts.mjs`; cwd repository root, exit **1**, stderr empty. Full stdout below; only the private absolute clone prefix is normalized to `<clone>`:

```text
TAP version 13
# Subtest: primary regression
ok 1 - primary regression
  ---
  duration_ms: 0.620524
  type: 'test'
  ...
# Subtest: healthy control
ok 2 - healthy control
  ---
  duration_ms: 0.133957
  type: 'test'
  ...
# Subtest: A1-A4: measured rows preserve order, formatting, empty output, escaping and producer parsing
ok 3 - A1-A4: measured rows preserve order, formatting, empty output, escaping and producer parsing
  ---
  duration_ms: 3.226181
  type: 'test'
  ...
# Subtest: A5: advisor report-table consumer escapes measured text and omits unmeasured rows
not ok 4 - A5: advisor report-table consumer escapes measured text and omits unmeasured rows
  ---
  duration_ms: 49.032356
  type: 'test'
  location: '<clone>/tests/test_sp1602_report_unknown_counts.mjs:36:1'
  failureType: 'testCodeFailure'
  error: "Cannot find package 'hono' imported from <clone>/server/analytics.ts"
  code: 'ERR_MODULE_NOT_FOUND'
  stack: |-
    Object.getPackageJSONURL (node:internal/modules/package_json_reader:314:9)
    packageResolve (node:internal/modules/esm/resolve:768:81)
    moduleResolve (node:internal/modules/esm/resolve:855:18)
    defaultResolve (node:internal/modules/esm/resolve:985:11)
    #cachedDefaultResolve (node:internal/modules/esm/loader:747:20)
    ModuleLoader.resolve (node:internal/modules/esm/loader:724:38)
    ModuleLoader.getModuleJobForImport (node:internal/modules/esm/loader:320:38)
    ModuleJob._link (node:internal/modules/esm/module_job:182:49)
  ...
1..4
# tests 4
# suites 0
# pass 3
# fail 1
# cancelled 0
# skipped 0
# todo 0
# duration_ms 147.373973
```

No package was fetched to turn that finding green. The report does not certify preserved semantics, full CI, scientific/visual/legal acceptance or retirement. Independent review remains required. The only repository change is this report; harnesses, dossiers, consumers, tests, archive, manifests and pins remain unchanged.
