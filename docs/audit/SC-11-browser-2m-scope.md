# SC-11: 2 m selected-copy browser acceptance

Status as of 2026-10-20: **NOT DEMONSTRATED — real-copy/browser recovery is
out of scope under the current allocation.** This satisfies SC-11's alternative
of documenting why execution is out of scope; it is not a browser PASS, a waiver
of the missing evidence, or closure of the underlying recovery issue.

## Why this audit does not run the recovery

The Fable audit's S1 / dossier item 11 reports browser acceptance at 4 m and an
unresolved 2 m selected-copy failure. The public recovery record is
[Grahammmm/skippercast#718](https://github.com/Grahammmm/skippercast/issues/718).
Its [latest disposition, 2026-10-19 15:13:29 UTC](https://github.com/Grahammmm/skippercast/issues/718#issuecomment-6270601237),
checked for this audit, states:

> Real-render copy status: not going ahead under the current allocation.

> Do not reuse the consumed hash-harvest, failed copy or native trial allocations.
> No artifact copy, browser, native run or shared-runtime adoption is authorized here.

SC-11 explicitly permits a documented scope exclusion. It supplies no new
manifest, private caller, custody/admission packet or finite recovery allocation.
Ordinary source/PR authority does not renew those consumed execution grants.
This audit therefore reads sanitized metadata and existing evidence only; it
does not copy private rendered artifacts, launch a browser/server, rerun the
pipeline, change the shared runtime or modify original receipts.

## What the evidence establishes

| Evidence | Established scope | Not established |
| --- | --- | --- |
| Original failed selected copy, described in #718 | One attempt exited at a compound length/full-stat equality assertion; no failed filename or before/after tuples were retained | Neither an atime-only cause nor unchanged content is proven; no successful transfer or browser acceptance |
| #718 source correction and [one-shot synthetic qualification](https://github.com/Grahammmm/skippercast/issues/718#issuecomment-6258915045) | The public handoff reports 30/30 synthetic tests passing at `bfa3a48cc64fc2e30e84e0e1e59ffbe44b2c6315`, zero retries | This audit did not rerun that consumed qualification; synthetic success is not real-copy/browser evidence |
| Archived T11 v4, `2026-10-19T18:35:32.265Z` | Two archived passes of the pinned legacy v1 Canvas 2D view, with T09 loader decode cross-check, interaction receipts and frame timing; archive checks rerun below | Not the held selected-copy lineage, current deployed renderer, full pipeline or user-facing performance |

The full-stat comparison includes access time, which a read can change without
content mutation. That sensitivity motivated the source repair; it does not
prove the cause of the original failed attempt.

### Do not conflate grid spacing with artifact lineage

The T11 v4 archive uses `SC26-001`, source `usgs-point-buchon`, survey year 2008.
Its hash-matching committed window is schema 1, 129 × 129, with `cell_m: 2.0`
and `native_cell_m: 2.0`. Thus it would also be inaccurate to relabel this archive
as a 4 m run merely because the audit's historical summary mentions 4 m.

These are distinct evidence records. The archive imports the legacy
`renderBottom` / `bottomSection` / `mountBottom` implementation whose controls
were removed from main by FE-61 (`dabb9c24`); T09 supplied the loader, not a
re-shipped view. Its view SHA256 is
`ad520d33e313b8d8b9dfb8634801c0160f68130bffef555344362a5898b4cbad`,
and its loader revision is `ddc891d0d7970103213724440831ae36389547a0`.
A 2 m spacing value on this different input and renderer does not establish
acceptance of the stopped private 2 m selected-copy path. The audit's unresolved
selected-copy finding stands. This note does not reconstruct or independently
certify the historical 4 m run.

The archived timing is requestAnimationFrame callback interval plus synchronous
control-draw latency, not rasterization throughput. The view uses Canvas 2D;
SwiftShader/WebGL presence does not make the archive a GPU performance test.

## Read-only verification performed for SC-11

Base inspected: `10ea2783f93099bb487d77f4cdfea9db084696e6`.
Node: `v22.23.2`. No browser execution was performed.

From the existing T11 evidence archive (locators below are archive-relative):

- `node verify-gates.mjs`: exit 0, `ALL GATE REGRESSION CHECKS PASSED`.
  Both archived passes satisfy the gates; all 11 no-op/dropped-control mutations
  are rejected.
- `node verify_evidence.mjs`: exit 0, `ALL CHECKS PASSED`.
  Source pins, input hashes, two pass summaries, interaction evidence and PNG
  signatures/dimensions were checked. This is archive revalidation, not a fresh
  browser run or independent visual inspection.
- `sha256sum` of the committed input window and index matches the archive's
  recorded hashes. Inspection of the matching window confirms the spacing above.

| Artifact (archive-relative unless otherwise stated) | Locally verified SHA256 |
| --- | --- |
| `summary.json` | `ddf517e7781ea675f6875ce6226003962fc16f1a894b82c55be3638ecb7cc165` |
| `pass1-evidence.json` | `93b5aea64d8623156804dea71283d19107e53f926191697ec4d2ace1d5916007` |
| `pass2-evidence.json` | `9c6cebc88259cf1d6a824475b4a3d88f51c3ddd4f9c2d510299b33fbd869b84a` |
| `pass1-screenshot.png` | `40e4c66f86380ce1df0d994934fde82d1f3865b9cc542d397783376640322902` |
| `pass2-screenshot.png` | `b11ed921ceb35af36166c73b6715cd7255dc78312ef9c8be419c5e2d52866798` |
| `gates.mjs` | `2d930302d4bda089f2a25206967eb152f641e875f7836d93af8ae74e0e4930be` |
| `verify-gates.mjs` | `a43e9be3b61207be7e837ecba75071ed4444bfaed7075c11dcd5de51c79a28ff` |
| `verify_evidence.mjs` | `4921b3084f780958565d2e2cb5b427a53eee646041d8552604a9ead6c8917c4b` |
| `ARCHIVE.md` | `c8c09a2036793547db00f33b02beb706357947de7bdfab5483eb818932f8a136` |
| Repository: `dist/regions/morro-bay/bottom/SC26-001.json` | `735eb3114789bd93e511008629276740bb74a524fd2316b54085b9d66829d553` |
| Repository: `dist/regions/morro-bay/bottom/index.json` | `59259b02e6c0b3de95d75b434ec482305c3b2535b20629c9fa16aef155cb3846` |

The original evidence remains with its existing custodian; no private artifacts
or internal host paths are published in this note. Relative locators and hashes
identify that retained archive, not files newly committed by this PR.

## Reopening the 2 m recovery

Continue through #718's existing ownership/custody lane; do not duplicate its
helper implementation or silently treat the T11 legacy archive as its successor.
Before any real-copy/browser attempt, the recovery owner must supply:

1. Fresh, explicit finite execution approval, preserving every prior failed or
   consumed allocation and its charges.
2. Current custody and sealed admission of supported source, destination and
   lock ancestry; denied or protected parents remain a stop.
3. The accepted exact transport-baseline hash manifest for the existing render.
4. The independently reviewed private caller/wiring bound to that manifest and
   approved helper.

Only then can a separately admitted attempt produce a verified copy receipt and
browser interaction, frame-timing and screenshot evidence for the exact 2 m
lineage, with cleanup/accounting and different-model review. The T11 target is
two passes, not a static preview alone. Until such evidence exists, report
**2 m selected-copy browser acceptance: NOT DEMONSTRATED**. No native, mapping or
rendering recomputation is authorized by this documentation.
