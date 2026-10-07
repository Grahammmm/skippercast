---
name: skippercast-build-coastal-map
description: Build and refine SkipperCast coastal fishing maps from reviewed terrain, habitat and marine conditions through bounded subagents, visual verification and live release. Use for shared 2D/3D map improvements, coastal data integration or product consolidation; use the focused ingestion or mapping skills alone for routine refreshes or survey-only expansion.
---

# Build a clear, beautiful coastal fishing map

Deliver a visitor-visible improvement: recognizable bottom structure, understandable
conditions, selectable species habitat and honest confidence. Use one geographic
batch or one shared interaction at a time. The map can emphasize relief for
readability; it cannot manufacture soundings, reefs, current measurements or catch
probabilities.

## Resume cheaply

Locate the user's canonical repository; read its `AGENTS.md`, current branch and
existing task ledger. In SkipperCast, start with `docs/FISH-MERGE-STATUS.md` or the
newer ledger it points to. Confirm actual main, deployed build, active owners and
relevant source identities. Dated receipts are historical evidence, not current
readiness. Preserve other agents' checkouts.

Keep **one existing ledger** with objective, scope, acceptance checks, decisions,
completed evidence, owner, exact blocker and next executable action. Add paths and
hashes instead of copying logs. A small CSS change does not need a new pipeline.
Choose the smallest batch that makes the map visibly better; do not rediscover all
sources or rebuild unchanged surveys.

## Route only what changed

Read these references on demand:

- Data binding, region rollout, integration or release: [pipeline](references/pipeline.md).
- Terrain seams, shaders, imagery, layers, pins or map inspection: [visual standard](references/visual-standard.md).
- Subagent assignment, model choice, stalled work: [orchestration](references/orchestration.md).
- Testing a lower model setting or improving this process: [calibration](references/calibration.md).

Use `skippercast-discover-data` for a missing authoritative source;
`skippercast-ingest-data` for reviewed adapters/refreshes;
`skippercast-map-coast` for measured habitat expansion/science changes;
`skippercast-add-region` for a regional package. Read only the relevant skill and
its needed reference. If absent, use the repository's corresponding contract;
report a missing required contract instead of improvising a scientific gate.

## Execute with bounded subagents

For substantial work, delegate genuinely independent source, renderer or review
work using the compact brief in orchestration. Usually one worker plus one
independent reviewer is enough; stay within the repository's delegation limit.
One owner integrates state, shared files and releases. Serialize browser use and
shared-file edits. Reuse agents only when their context and settings fit; do not
spawn a team for a trivial edit. Never create user-owned chats for internal work.

Use scripts for deterministic fetch/normalize/hash/validate/build work and for
waiting on jobs. Select supported model/effort pairs from orchestration; preserve
explicit user settings. The table is a starting hypothesis, not a proven minimum.
Calibrate against actual pass/fail evidence before lowering a consequential task.

After a repeated failure with no new evidence, save its fingerprint and change
method, move to an independent task, or report the external need. Do not continually
refresh snapshots or rerun an unchanged rejected import to appear busy. A blocked
source can leave its layer withheld while other map work proceeds. No model
setting can resolve missing authorization or an unavailable external service.

## Acceptance before calling it done

- Data: original rights, hashes, geographic binding, depth datum, native support,
  units, masks and observation/issue/valid/retrieval clocks survive. Missing data
  remain identifiable. Modeled fill is distinct from measurement.
- Design: actual harbor, shoreline, reef and regional views are readable; no
  terrain spikes, void cliffs, imagery seams, oversized labels or control overlap.
  Source inspection reports native values even with relief emphasized.
- Interaction: one place/profile/target/time state; camera-only 2D/3D toggle;
  zoom-dependent habitat regions and compact selectable pins; clear details and
  confidence; relevant Boat/Shore/Spear conditions. Existing unique capabilities
  survive a merge and overlapping controls are consolidated.
- Evidence: run relevant deterministic checks plus required repository gates;
  inspect actual desktop/mobile rendering through supported browser access and
  obtain required independent review. A build or screenshot alone is insufficient.
- Live, when authorized: protected exact-head merge, required main CI, existing
  Cloudflare workflow and actual deployed revision/data/interaction readback.
  Report partial integration or unavailable layers explicitly.

Finish with what changed for the fisherman, checks passed, meaningful remaining
gaps and next action. Save a screenshot when it helps demonstrate the result.
Do not claim all coastline is mapped, all features are merged, safe boating or
likely catches merely because the map is beautiful.
