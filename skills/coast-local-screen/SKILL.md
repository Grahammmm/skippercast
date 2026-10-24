---
name: coast-local-screen
description: Screen every admitted coastal window with deterministic measurements and explicitly qualified local text and vision evidence in an immutable review attempt.
---

# Purpose

Tier 1 flags evidence for independent review; it does not accept maps, sources,
a campaign, or a live run. This is the canonical round-addressed adapter to the
existing screener, not a second set of raster or reply-parsing algorithms.

Governing contracts: [coastal discovery](../skippercast-discover-coastal-sources/SKILL.md),
[coastal mapping](../skippercast-map-coast/SKILL.md),
[shared contracts](../coast-campaign-shared/references/contracts.md), and
[directory layout](../coast-campaign-shared/references/directory-layout.md).

# Runs on

The card-admitted local-worker route, with independently established local vision
capability. A model alias, standalone image bake-off, or a profile name does not
prove actual runtime identity or Hermes image-tool qualification. Unavailable or
held routes stay held; no cloud fallback. Tests use labelled synthetic replies,
not inference. These drafts grant no service, model, cap, or installation changes.

# Inputs

From the pinned checkout, use its registered shared interpreter SC_PY. The card
binds absolute ROOTS, CTX, and R (the exact `plans/<plan_id>/review/rNN/aNN`
attempt), plus explicitly approved ENDPOINT, MODEL, VISION_MODEL, and SLOTS.
ROOTS is operator-selected deployment metadata, never receipt-selected paths;
it must contain exactly the context's admitted, disjoint root IDs. Every data
read is confined/no-follow and hash-checked. No real source download is allowed.

CTX must be produced by the reviewed `coast-sign-off` prepare_round command.
Use that skill's installed command contract, including its required independent
allowed-root IDs; the shortened historical design example is not its full CLI.
Context pins admission, shared v2 run/enqueue adapters, bridge, posted evidence,
thresholds, routing and exactly one `text.md` and `vision.md` prompt. Native PC-9
v1 bytes are preserved and checked through `coast_receipt_versions`, never
rewritten. Context/run/config identity failures refuse screening and require the
existing integrity-error/corrective review path; they are not empty clean results.

The launcher also supplies COAST_AUTHOR_PROFILE, COAST_AUTHOR_MODEL (actual
runtime, not the requested endpoint alias), COAST_CARD_ID, COAST_CODE_COMMIT,
and COAST_SKILL_COMMIT. Assembly refuses missing provenance. The final receipt
uses that runtime header; endpoint model aliases are separate telemetry.

# Exact commands

All file arguments below are absolute card bindings. Run from SC_REPO. The
legacy `--plan-dir`, `all`, latest-run lookup and mutable default thresholds are
forbidden in this skill; they remain solely for backward compatibility tests.

```sh
"$SC_PY" skills/coast-local-screen/scripts/local_screen.py stats --roots "$ROOTS" --context "$CTX" --out "$R/tier1/stats.json" --thumbnail-dir "$R/tier1/windows"
"$SC_PY" skills/coast-local-screen/scripts/local_screen.py text --roots "$ROOTS" --context "$CTX" --stats "$R/tier1/stats.json" --endpoint "$ENDPOINT" --model "$MODEL" --slots "$SLOTS" --out "$R/tier1/text.json"
"$SC_PY" skills/coast-local-screen/scripts/local_screen.py vision --roots "$ROOTS" --context "$CTX" --stats "$R/tier1/stats.json" --endpoint "$ENDPOINT" --model "$VISION_MODEL" --slots "$SLOTS" --out "$R/tier1/vision.json"
"$SC_PY" skills/coast-local-screen/scripts/local_screen.py assemble --roots "$ROOTS" --context "$CTX" --stats "$R/tier1/stats.json" --text "$R/tier1/text.json" --vision "$R/tier1/vision.json" --out "$R/tier1/flagged-windows.json"
```

Outputs are canonical sorted finite JSON with newline, O_EXCL and fsync.
Thumbnail and response descendants are preflighted before work. Existing or
partial outputs require a newly prepared attempt, never overwrite or cleanup.
Responses are canonical JSON envelopes in `windows/<sha256(window_key)>/text-response.txt`
and `vision-response.txt`; the `.txt` envelopes are opaque graph leaves whose
identity and typed producer/context bindings the adapter checks explicitly.
They retain normalized raw reply/error evidence, prompt Ref, endpoint/model,
verdict, latency and token measurements. They are not independently authenticated
proof of the model's actual identity. Failed HTTP/malformed envelopes retain a
diagnostic rather than inventing a visual assessment.

## Intermediate shapes (owned by B2)

All three use `schema: coast-tier1-canonical-v1`, `mode`, `context` Ref, `run` Ref
and ordered `windows`. These are internal shapes, not new shared schemas.
`_validate_intermediate` checks exact envelope/row fields, typed Refs, the shared
Tier1 window shape and telemetry shape; the positional binding gate checks
semantics. They are not passed as standalone shared workflow receipts.

- stats: also `thresholds` Ref; each row has `window_key`, nullable `producer`
  Ref, and `entry` in the shared Tier1 window shape, before model evidence.
- text/vision: also `stats` Ref and `telemetry`; each row has `window_key`,
  nullable `producer`, nullable `response` Ref, `verdict` and nullable `error`.
- Final `flagged-windows.json`: the unmodified `coast-tier1-screen-v1` schema.
  All admission positions appear once. Producer `depth_m` count/min/max/mean/p80
  are copied verbatim, including `unknown`, with exact field paths and Refs.
  There is no invented producer median or new shared schema field.

# Acceptance checks

Every output hash must match the posted handoff. Final receipts validate with
`validate_coast_receipt`; that is structural evidence, not semantic acceptance.
Check all admitted windows, explicit producer/position binding, separate source
and grid identities, immutable prior attempt bytes, and exact context inputs.
Wrong-window stats/model envelopes refuse with WINDOW_BINDING before final output.

Required mapped measurements distinguish measured from unavailable. Structural
no-neighbour and absent optional catalog range are not_applicable, not measured
passes. Missing expected neighbour evidence is unavailable and flags. Held and
unfinished windows remain held/unavailable, never pass. Adjacency uses native
pixel offsets within the same source/grid and plan; no cross-plan/global-index
qualification is implied. Terrain derivation uses the existing bounded raster,
hillshade (256 pixels, azimuth 315, altitude 45), edge and deterministic rules.

Model replies can never clear deterministic flags or pipeline holds. Anything
other than a complete parsed pass is non-pass. Missing endpoint/thumbnail or
malformed response flags; missing raw evidence cannot claim pass. Canonical
mode uses at most two 60-second POST attempts before opening its endpoint circuit;
no additional model-list probe. It consumes sequentially, recording SLOTS as the
admitted ceiling rather than granting concurrency. No model network calls occur
in offline acceptance tests.

# Failure modes

Exit 2 means a refused precondition, corrupt or incompatible input, wrong window,
symlink, missing provenance or existing output; retain the attempt and hand it
back, never rerun into it. Endpoint unavailability is instead recorded as
ENDPOINT_UNAVAILABLE for every mapped window and can produce a valid flagged
receipt. Null required derivations are DERIVED_UNAVAILABLE, never false negatives.
Schema-valid is review-required. Invalid input pins go to corrective integrity
review, not to model judgement or a smaller denominator.

# Metrics emitted

Final status counts cover pass_count/flag/held/unavailable. Per-mode telemetry
records measured wall time, nullable token total, endpoint, requested alias,
prompt SHA and admitted slots. The shared final schema has one telemetry slot:
model and endpoint strings contain a JSON text/vision mapping; prompt_sha256 is
the SHA of the canonical text/vision prompt-hash mapping. Individual actual
prompt Refs and per-mode values remain in response envelopes. Unknown tokens stay
null; these measurements do not establish recall, accuracy, live model capability
or independent review. Post the final file hash separately (no self-hash).

# Never

Never change producers, source pins, Store/policy/caps, hosts, defaults, ledgers,
installed skills or model routes. Never delete job or attempt directories,
download, publish, email, or start a pilot. Never infer readiness from machine
validity, turn held/unavailable into pass, treat an alias as actual runtime proof,
or override the sole independently qualified Tier3 reviewer.
