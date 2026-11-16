# Run218 receipt / preview locator (AUDINV-FIX-125)

Read-only locator report. Checked main `d75aa3a52fdde19564ca60176966525adbf5202a`; lookup run 2026-11-15 by task t_4925aab4.
No rerender, no fresh run, no render allowance, no attachment or send, no review request, no source access. This report is not approval of anything.

**Verdict: ARTIFACTS NOT LOCATED. Documented-only.** Neither the run218 receipt nor any preview was read back. HOLD for the custodian (below).

## Identity being located

| Field | Value | Basis |
| --- | --- | --- |
| Card | T13 `t_189fbd03` (done) | `skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md:303` |
| Run | run 218 (deepseek), render PASS 07:18Z | `$HOME/agent-work/NEXT-ITERATION.md:310,322` (historical notes; `$HOME` replaces the private local home root) |
| Receipt locator | `outputs/t13-four128-terrain-acceptance-20261020/t13-receipt.json` (relative private-store locator) | coastal-pipeline.md:303 |
| Full receipt hash | `d80ecebab98004e79c6bb4d5b7c6015fed21f442c64ef0283dee714b22b80e94` | task spec; the tracked doc itself gives only prefix `d80ecebab980` |
| Recorded facts | PASS, 4 cores, 0 held, generated `2026-10-20T07:18:22Z`, renderer `ed28dc69` | coastal-pipeline.md:303 |
| Preview locator | `render/preview.png` (historical hint only, relative to the run output; NOT confirmed placement) | NEXT-ITERATION.md:310,322 |

The hint path in the card body (`outputs/.../t13-receipt.json`, `render/preview.png`) is a hint. It is not guaranteed actual placement, and no retained receipt reference that states the actual placement was found.

## Lookup table

Allowed lookup roots: only two exact roots, each named by retained metadata. There was no filesystem-wide or HOME search.

1. `$HOME/skippercast-data/2026-10-07-pge-south/repo` (the authoritative checkout named in `AGENTS.md:212`).
2. This builder clone of main (tracked files only; its docs say outputs are private-store locators, "not files shipped in Git", coastal-pipeline.md:230).

| Requested artifact | Recorded locator / full hash | Root | Observed path / hash / size | Status |
| --- | --- | --- | --- | --- |
| T13 receipt | `outputs/t13-four128-terrain-acceptance-20261020/t13-receipt.json` / `d80ecebab98004e7...b80e94` | root 1 | MISSING: root exists, but has no `outputs/` directory | no original, no copy |
| T13 receipt | same | root 2 (clone) | MISSING: no `outputs/` directory in Git | not shipped in Git, as documented |
| Preview | `outputs/t13-four128-terrain-acceptance-20261020/render/preview.png` / no hash recorded | root 1 | MISSING | no original, no copy |
| Preview | same | root 2 (clone) | MISSING | not shipped in Git |
| Per-core `core-{A,B,C,D}/acceptance.json` (prefixes `b0541830a9f0`, `ff2b98370be0`, `ec482896f6d3`, `b833919c882a`) | coastal-pipeline.md:315-318 | root 1 and root 2 | MISSING in both | prefix only, never full identity |

Binding confidence: **none** (nothing was observed). Observed hash, size and original/copy status do not exist; none are fabricated.

## Edge-case findings

1. **Docs present, artifact absent:** documented-only. The tracked doc is a record, not artifact readback.
2. **Preview without matching receipt:** no preview was found, so none can be bound. Any later preview found without the matching full-hash receipt stays unbound.
3. **Hash mismatch:** none observed (no bytes read). A later mismatch means conflict/HOLD, with no overwrite or replacement render.
4. **Multiple run218-like paths:** not seen. Several candidates later would be ambiguity, not first-match success.
5. **Prefix hashes:** the tracked doc carries 12-hex prefixes only. They cannot substitute for the full identity `d80ecebab98004e7...`, which in this report comes from the task spec, not an independently read artifact.
6. **Review status:** Opus vision review "completed/approved on t_189fbd03" is documentary and historical, and the review scope has expired. It is not current approval. A missing attachment cannot trigger a rerender: NEXT-ITERATION.md:310,322 already say the retry should only attach/request review.
7. **No admitted root beyond the two above:** no other location was searched. Any other location must be supplied by the custodian.

## Missing evidence and custodian

- Missing: the retained private-store location of `outputs/t13-four128-terrain-acceptance-20261020/` (receipt and PNG previews). Not present at the two roots above.
- Custodian: the coastal pipeline coordinator / private-store owner (the operator who ran T13 run 218). Please supply an exact admitted root; a follow-up locate-only pass can then table observed hash and size against the full hash above.
- Unchanged holds: publication_prohibited, machine-valid is review-required, and no rerender or new render allowance follows from this gap.
