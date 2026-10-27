# Pinned C3 / real C2 diagnostic

This is a local browser diagnostic, not a production viewer or a scientific,
rights, datum, support-preservation, or publication acceptance.

`probe_c3_real.py` reads the admitted C1 manifest and the completed C2 producer
receipt; their exact input hashes must agree. It snapshots existing C2 tiles
without generating contours or modifying any upstream cache. It reads the exact
C3 `mvp.ts` and `palette.ts` from the specified Git SHA, leaves those bytes
unchanged, and emits JavaScript with an explicitly supplied **durable** installed
TypeScript compiler. `--noCheck` is an emit-only step, not `pnpm check` or a full
product typecheck. It rejects dependency roots inside disposable worktrees or
kanban workspaces. It does not install, download or link a node_modules tree.

Only MapLibre's existing browser distributions are copied into the private
packet, with hashes. The same durable installation supplies Playwright at its
absolute path. An ephemeral loopback server serves only the copied packet;
Playwright blocks non-local page requests. Browser and server are stopped in
`finally`. The test Chromium uses `--no-sandbox` because the host does not expose
usable user namespaces; this per-process choice is explicit in the receipt and
does not modify host or profile security settings. Do not point it at remote or
untrusted pages.

From the repository root (existing survey interpreter):

```sh
python -m research.scripts.coast_mvp.probe_c3_real \
  --repo /task/repo --c3-head <exact-40-hex-reviewed-C3-head> \
  --c1-manifest /admitted/c1/manifest.json \
  --c2 /admitted/c2/baseline --c2-receipt /admitted/c2/baseline-receipt.json \
  --dependencies /durable/repo/node_modules \
  --output /task-owned/new-c3-diagnostic --browser /installed/chromium
```

The native C1 adapter preserves source notices and datum caveats verbatim and
sets every source's permission hold true; it does not infer licensing clearance.
The C3 manifest identifies these inputs as real, not synthetic. C2 metadata's
existing limitations are retained in the machine receipt, including any stale
synthetic/local-preview boilerplate. The run receipt, not that boilerplate,
binds the real C1 hashes.

## Actual render proof, not just a screenshot file

At three viewpoints, the driver waits for MapLibre idle in real browser time,
records decoded vector-feature counts, captures the screenshot, and toggles the
real contour layer to prove that rendered canvas pixels change. Page exceptions
or missing contour geometry/pixel effects fail the execution. The earlier
Chromium CLI virtual-time attempt did not wait for GPU/worker readiness; its
empty loading screenshot was rejected rather than relabeled as a render.

Separately, deterministic sample coordinates are derived from alpha=0 pixels in
the actual C2 PNGs. If the loaded viewer returns finite terrain at those points,
the receipt says `unsupportedRendered: true` and the screenshot explicitly says
**SUPPORT GAP / DIAGNOSTIC ONLY / not display-accepted**. This is a defect probe,
not a support-area metric. A successful diagnostic process never suppresses
that finding. Sparse absent vector tiles and their actual HTTP 404s are retained,
not replaced with fabricated tile data or counted as successful fetches.

The first actual C3-on-real-C2 run on 2026-10-22 exposed severe boundary curtains
and finite terrain at transparent pixels in all three views. Fixing C3 support
handling belongs to the follow-up task; this script does not silently change
source depths, masks, C3 code, or source datums to conceal the failure. The
separate C1 hillshade fallback preserves unsupported cells and remains the honest
static preview. Do not publish the diagnostic or infer scientific acceptance.

Real data, screenshots, tiles, generated browser assets and receipts remain
private task attachments, not source-repository files. Only these tools and
synthetic tests belong in the PR.
