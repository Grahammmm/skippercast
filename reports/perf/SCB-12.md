# SCB-12 — start the map in parallel

**MEASURED: canvas target passes locally:** median 4.865 s; every cold run is <=5.0 s ([4871, 4771, 4865, 4749, 4915] ms). Baseline main was 7.610 s (3 runs). Not merged, deployed or verified live.

**MEASURED trade-off:** verdict changes by 692 ms; review this explicitly. This is a map-start improvement, not a claim that the whole first visit is faster. SCB-11 owns brief startup. Fully drawn below means the existing first-idle mark, not proof every later async overlay has arrived.

| Cold median | main 114079ae (n=3) | candidate 036340dce1 (n=5) |
|---|---:|---:|
| canvasMs | 7610 | 4865 |
| verdictMs | 7466 | 8158 |
| chartIdleMs | 19943 | 19680 |
| bytesToVerdict | 960698 | 1232282 |

## Change and preserved boundaries (READ)

A dependency-free Vite entry starts the existing MapLibre wrapper and mandatory app graph concurrently. Explicit terrain choices, unchosen homes and non-map pages stay lazy. The store still resolves saved homes, aliases and terrain fallbacks. Library failure cannot block the app, and createChart owns its existing failure panel. No handwritten preloads, new providers, service changes or credentials.

Aerial and seafloor downloads wait for the existing first brief epoch to seal, including failure/timeout. The latch never re-holds imagery during refresh. Seafloor publication/rights/held-source checks run unchanged after release. Initial idle/flyover does not claim completion while imagery is deliberately held. The mandatory app graph still counts in startup budgets and landing warm assets.

The new asynchronous entry exposed a stylesheet cascade reversal (MEASURED: UI sheet defaults overwrote the phone app's 176px peek/56px bottom). The existing ordered-page stylesheet plugin now also handles ../web/ paths. Its repaired 320px computed geometry matches main; the existing phone shell/axe browser test and both new real-bootstrap browser tests passed (3 tests). Unmodified main passed the same shell test; earlier candidate failures are preserved, not hidden or skipped.

## Method and limits (MEASURED unless stated)

Built actual Vite assets served with Brotli over local HTTP; public live GET fallthrough for feeds, map files and real external aerial tiles. No synthetic feed responses, stubbed aerial images or route-fulfilled app downloads. Same server/harness for baseline and candidate. CDP: CPU 4x; latency 150ms; down 204800 B/s, up 96000 B/s; 390x844, DPR3, touch/mobile UA. Fresh browser context per cold run, same-context warm tab three seconds later, one browser at a time. Flyover is enabled. DOM canvas marker, actual verdict marker and existing chart-idle mark match SCB-02's script. Raw timings/request logs, scripts and rejected trials are in the card evidence archive and local results folder.

This is emulation on a loaded shared host, software WebGL, one region (Morro Bay), not G's real phone. Local HTTP transport/Brotli differs from production's edge/HTTP2 compression. Public upstream data can change between runs. Baseline n=3 includes a slow first run; candidate n=5. Re-measure live after a reviewed merge before calling the production target verified. The audit's proposal to relax to 6s was not adopted.

## Verification and rollback

Typecheck, real build, client asset/budget checks, check_web and local CI contracts/repository checks passed. Full bounded installed prepush gate and remote exact-head CI are recorded in the review handoff, not assumed here. Existing phone shell browser coverage passed at all its viewport presets; new held-main/library-failure browser tests passed. Candidate build: 036340dce1. No budget raised or tests skipped.

Rollback: revert this one PR through the usual reviewed path. No live switch, database migration or service restart is involved.
