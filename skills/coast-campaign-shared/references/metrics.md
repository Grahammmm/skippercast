# Pilot metrics contract (review required)

Rev4 replaces the historical section-6 metrics definition with section 5;
section 6 now defines lifecycle. Both sections below are preserved verbatim
from the admitted rev4 pin c8fabf7e2e1451af762ee9c9e52c32cab5831877e34cae3f7a5a98b00bb6d433.
These drafts are pilot-programme tooling, retired after long runs start.

## 5. Statistics and readiness populations

Producer fields stay verbatim with source Ref and field path; cells depth_m has count/min/max/mean/p80, NOT median/p99. Derived required measurements for map_done: valid_fraction, depth_median_m, depth_p99_m, nodata_fraction, edge_valid_fraction, slope_p99_deg; bounded to admitted terrain/support <=262144 cells. Each measurement is {status:measured|not_applicable|unavailable,value:number|null,reason:null|string,inputs:[Refs],method_version}. No bare ambiguous null.

Neighbour delta is not_applicable with reason=no_geometric_neighbours only when the verified grid has none; it does not flag and cannot inflate a measurement denominator. Missing expected neighbour data is unavailable -> DERIVED_UNAVAILABLE flag. Catalog depth range absent is optional not_applicable/catalog_range_absent, never counted as a successful plausibility test; a stated range that cannot be evaluated is unavailable. Required raster read/derivation failure is unavailable -> flag; no model can override it. For held/unmapped windows raster statistics are not_applicable/pipeline_not_mapped and Tier1=held or unavailable, not pass. Endpoint absent/malformed response/missing visual assessment on map_done => flag, raw response retained; no inferred visual pass. Thumbnail deterministic 256x256, hillshade azimuth315/altitude45, nodata transparent, renderer/version pinned. Model and endpoint capability remain explicitly qualified parameters, not hard-coded proof of vision support.

Let W = ALL distinct admitted inventory windows in the selected cycle/cohort (deduplicate replacement attempts with original inventory key). Missing run summary does not remove W. A = windows with verified acquire.done; Q = verified qualify.done with holds empty. Mandatory invariants Q subset A subset W. Output counts W,A,Q plus acquire-held/failed/pending/missing; acquire-done-without-qualify; qualify-held/failed/pending; map-held; integrity-unavailable and replacement exclusions.

qualify_clean_all_admitted = |Q|/|W|. This ALONE tests the readiness >=95% criterion, with every hold also requiring accepted cause. Zero W => not measured, NOT pass.
qualify_clean_given_acquire_done = |Q|/|A|, labelled conditional; zero A => not measured. Never label this the all-window readiness rate. Optional attempted-qualify metric must be separately named; it never replaces either rate. Unknown evidence contributes no numerator, remains in W, and makes evidence completeness fail.

Controls (one cohort with 4 windows): acquire-held; acquire.done/qualify absent; qualify.done/map held; qualify.done/map done. W=4,A=3,Q=2 => all-admitted 0.5, conditional 2/3; map_done=1; acquisition-held/pending qualify must not disappear. A single mapped isolated window with every REQUIRED measurement available and neighbour status not_applicable can pass Tier1. A mapped window missing a required measurement stays flag even if a reviewer accepts the explanation for record closure; it is NOT a true negative or a quality pass.

Confusion population: only reviewer-examined mapped windows with valid integrity and complete REQUIRED measurements plus definite reference decision. tp=Tier1 flag/reviewer defect; fp=flag/no defect; fn=pass/defect; tn=pass/no defect. Explicit lists/counts: held, unavailable-required, unfinished, invalid-evidence, unexamined, reference-undetermined. Accepted closure cause is not a negative quality label. Optional not_applicable is not exclusion. Report recall tp/(tp+fn), precision tp/(tp+fp), misses=fn, population definition and sampling bias. Zero denominator => not measured. These are examined-population metrics, NOT measured whole-coast recall. A readiness audit must state sampling limits and unmet coverage, never claim 90% detection over unexamined windows.

Readiness outputs, all with evidence Refs:
- hashes/broken receipts from T1/T2/open-report, no invalid evidence counted clean;
- >=95% all-admitted qualification and hold cause dispositions as above;
- screener recall/precision + misses over named examined cohort;
- no sampled must-fix, with sampled count (zero sample is not visual evidence);
- contour/seam visual criterion NOT supplied by hillshade stats: not measured until separately reviewed contour/preview artifact exists;
- N=16 time/bytes requires real PC-6 N=16 run, not dry-run or held receipts;
- review rounds per original plan inventory, median from actual verdicts;
- throughput = distinct final accepted plan inventories / elapsed observation days, not number of corrective verdicts; report mapped and accepted-held throughput separately;
- projection from measured windows/plan/remaining admitted inventory, not guessed plan counts; cache peak across campaign, tokens/latencies measured, missing cost remains unknown;
- operator rescues from board events with scope/period, unavailable if no event export.
Interim pilot files are labelled interim with explicit adapters; absent counts/images/provenance remain unavailable, not silently upgraded to canonical measurements.

## 6. Card lifecycle and tier roles

Per admitted plan: RUN -> T1(local-worker) -> T2 rehash/budgets/neighbours (bounded luna/haiku checks in parallel) -> T2 assemble -> V-/T3 independent semantic reviewer. Every edge is a kernel parent edge, all outputs round/attempt-addressed. Local GPUs do the bounded first pass on every window before T2/T3; no duplicate local queue jobs or assumptions that unavailable image tools work. Operator alone raises concurrency (target 3-4 local slots and swarm widths are measurements, not granted caps). CPU/network mapping and model-review time reported separately.

T3 is a separate card with completed parents, so it never calls request_changes on a RUN parent. It writes verdict then:
- accept: create authorized next admission child (or close-preparation after full inventory closure), complete current V- with evidence, not a publication declaration;
- must_fix: create correction child with exact numbered findings and pins, then fresh r+1 T1/T2/T3 chain. Complete current V- as 'review completed: must_fix', not plan accepted. Content changes require new admission/plan identity; review-only changes retain plan and new round. Third bounce goes to fable-2nd-look, not an endless fourth review;
- external blocker: block current task only for actual unavailable endpoint/medium/required decision that cannot be corrected locally. An integrity defect is corrective must_fix, not an external block.

Scripts print suggested board actions; agents perform them via kanban tools and read back. Do not embed created_card IDs in a prewritten immutable verdict: verdict contains action kind/next inventory authorization; board IDs go in the subsequent handoff. This avoids rewriting verdict bytes after creating cards. Readiness approval remains the Claude operator's; no skill auto-starts long runs, publishes, emails or changes operational routes.


## Rollup input contract

The exact argv is in coast-pilot-audit/SKILL.md. All paths are absolute.
The card supplies a frozen cohort JSON and root bindings separately. No latest
file glob selects canonical evidence. The cohort is operator-selected deployment
metadata, not scientific acceptance, and must enumerate ALL admitted inventory
plans for the cycle, including held and missing-run plans:

    {"schema":"coast-metrics-cohort-v1",
     "allowed_root_ids":["queue:campaign-id"],
     "plans":[{"admission":Ref,"runs":[Ref],"verdicts":[Ref]}],
     "ledgers":[Ref],"measurements":{}}

Ref has exactly root_id/path/sha256/bytes. Each queue binding must be
COAST_ROOT/campaign_segment_id. Other admitted namespaces remain disjoint.
The cohort and roots JSON are explicit operator inputs, never receipt-discovered
bindings. Protect their handoff bytes independently before running this command.
Every receipt uses the shared no-follow resolver, schema and full graph validator;
corrective error verdicts retain identity_snapshot semantics. The reader adds no
bindings, fetches no source and never writes a ledger or board database.

Runs are explicitly ordered continuation snapshots, sequence 1 onward. An empty
runs list means missing execution evidence, NOT an empty inventory. A broken run
retains its admission windows in W, adds broken_evidence and contributes no A/Q.
A done stage needs a hash-verified native result matching stage/job/segment/input
manifest/state/holds. Q requires verified acquire.done and qualify.done without
holds; no inference from map_done. Unknown or pending qualify is not clean.
Verdicts are explicitly ordered (review_round, attempt), with actual model policy
validated through trusted_context/reviewer. The final verdict must bind the final
run. Historical verdicts supply rounds/minutes, never extra accepted plans.
Ledgers are pinned segment AND independently chained campaign-index snapshots;
throughput acceptance requires both rows pointing to the final verdict. Snapshot
copies may be kept inside an admitted root; the rollup never reads mutable Store
state. Missing ledger evidence cannot authorize acceptance.

replacement_plan_of is the exact original admission Ref, as in the shared schema.
All originals/replacements must be in the cohort. Linear replacement chains with
unchanged inventory keys are deduplicated by the original inventory. Changed grid
or window inventory requires upstream explicit reconciliation and is REFUSED,
not matched heuristically. Duplicate ownership, missing original, branches and
cycles refuse. Older r1 files remain untouched. Historical runs/reviews can be
retained without counting as another final plan. An empty cohort reports zero W
and unavailable rates. Cohort completeness is an operator precondition; an
omitted plan cannot be discovered from directories or a success-only subset.

--since is UTC with timezone. The frozen cohort defines the selected inventory;
it is not reduced when a plan began before --since. The observation interval for
throughput starts at --since and ends at the latest selected final verdict time;
only distinct final accepted inventories finishing inside it enter the numerator.
Zero/nonpositive elapsed time is unavailable. Accepted-held and fully mapped
throughput are separate. Pipeline wall/bytes sum explicitly selected continuation
executions; model latency and tokens remain separate. Review rounds are distinct
(plan_sha256, round) per original inventory; attempts do not inflate rounds.
Reviewer minutes sum actual verdict minutes over its historical review chain.
Tier2 accuracy is the unweighted mean of final verdict-provided measured values,
with measured populations and unavailable-plan count; self-confirmed T2 flags are
not an accuracy reference. No missing value is silently converted to zero.

Optional --interim reads only cycle-1 tier1-*-D1/M2/S1.json and
packet-*-D1/M2/S1.json entry names. It accepts the old run/generated_at/files/
posted_sha256_compare/gate_fields/rows/thumbnails/deterministic_flags/model_flags/
wall_seconds and packet run_id/review_window/hashes/flags_confirmed/flags_total
shapes. Absolute paths INSIDE them are provenance strings, NEVER followed.
Historical before-second-look copies are not extra observations. Retained values
are labelled interim producer observations, never upgraded to canonical hashes,
qualification or confusion. Missing provenance/counts/images/tokens stay unknown.

Optional --board-events accepts a complete, cohort-bound export:

    {"schema":"coast-board-events-v1", "since":UTC, "until":UTC,
     "cohort":InputRef, "events":[{"id":String,"created_utc":UTC,
                                   "operator_rescue":Boolean}]}

InputRef is the hash/bytes of the exact cohort file with root_id=input:filename
and path=filename. Events are unique and in period. Absence means unavailable,
not zero rescues. The export's complete scope is an operator precondition.

Supplementary measurements may be supplied by name in measurements as Refs to
coast-pilot-measurement-v1 envelopes. Their keys are schema, metric, measurement,
population, evidence (nonempty Refs), reviewer_verdict (a valid accepted canonical
verdict). measurement is {status, value, reason, method_version}. Only actual,
separately reviewed contour/preview, PC-6 N16 execution, campaign cache peak,
measured token-cost or measured inventory/throughput projection evidence belongs
here. An audit must still check the method and population; the rollup is not
semantic acceptance. Absent supplementary evidence is not measured. Hillshade
stats do not supply contours; dry-run/held runs do not supply N16 performance;
per-plan usage does not supply campaign peak; missing cost stays unknown.

Supplementary evidence must occur in the accepted independent review's decision
evidence, not merely beside an unrelated verdict. N16 additionally requires a
full-graph verified actual 16-window run with acquire/qualify/map done for every
window; the boolean must match its actual admission time and byte budgets.

## Output contract

Every metric is {status, value, display, reason, population, evidence}. Unavailable
and N/A value is null and display is "not measured", never pass. Measured values
are numbers or criterion booleans. Ratios report numerator and denominator.
inventory gives W/A/Q, window identities and selected evidence, replacement
exclusions, and named stage exclusions with counts AND lists. confusion gives
counts, named groups, examined population and sampling limits. producer_fields
are verbatim and source-addressed; derived_measurements stay separately labelled.
final_plans counts inventories, not verdicts. diagnostic_findings/broken_evidence
retain invalid evidence, not cleaned-up successes. review_required is always true.
No output grants readiness, operational routing, publication or long runs.

The following JSON Schema is the machine-checkable output envelope. Nested
receipt-derived populations retain their shared producer schemas. Tests check the
population invariants in addition to this envelope.

<!-- OUTPUT-SCHEMA -->
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema",
    "since",
    "review_required",
    "limitations",
    "evidence_complete",
    "inventory",
    "confusion",
    "holds",
    "final_plans",
    "diagnostic_findings",
    "broken_evidence",
    "producer_fields",
    "derived_measurements",
    "interim",
    "metrics"
  ],
  "properties": {
    "schema": {
      "const": "coast-pilot-metrics-v1"
    },
    "since": {
      "type": "string"
    },
    "review_required": {
      "const": true
    },
    "limitations": {
      "type": "string"
    },
    "evidence_complete": {
      "type": "boolean"
    },
    "inventory": {
      "type": "object"
    },
    "confusion": {
      "type": "object"
    },
    "holds": {
      "type": "array"
    },
    "final_plans": {
      "type": "array"
    },
    "diagnostic_findings": {
      "type": "array"
    },
    "broken_evidence": {
      "type": "array"
    },
    "producer_fields": {
      "type": "array"
    },
    "derived_measurements": {
      "type": "array"
    },
    "interim": {
      "type": "array"
    },
    "metrics": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "qualify_clean_all_admitted",
        "qualify_clean_given_acquire_done",
        "map_done",
        "screener_recall",
        "screener_precision",
        "screener_misses",
        "sampled_must_fix",
        "review_rounds_median",
        "reviewer_minutes_per_plan",
        "tier2_packet_accuracy",
        "accepted_plans_per_day",
        "mapped_plans_per_day",
        "accepted_held_plans_per_day",
        "pipeline_wall_s",
        "pipeline_bytes",
        "local_tokens",
        "local_latency_s",
        "contour_visual_clean",
        "n16_within_budget",
        "cache_peak_bytes",
        "token_cost",
        "projected_coast_days",
        "operator_rescues",
        "broken_receipts",
        "hash_mismatches"
      ],
      "properties": {
        "qualify_clean_all_admitted": {
          "$ref": "#/$defs/metric"
        },
        "qualify_clean_given_acquire_done": {
          "$ref": "#/$defs/metric"
        },
        "map_done": {
          "$ref": "#/$defs/metric"
        },
        "screener_recall": {
          "$ref": "#/$defs/metric"
        },
        "screener_precision": {
          "$ref": "#/$defs/metric"
        },
        "screener_misses": {
          "$ref": "#/$defs/metric"
        },
        "sampled_must_fix": {
          "$ref": "#/$defs/metric"
        },
        "review_rounds_median": {
          "$ref": "#/$defs/metric"
        },
        "reviewer_minutes_per_plan": {
          "$ref": "#/$defs/metric"
        },
        "tier2_packet_accuracy": {
          "$ref": "#/$defs/metric"
        },
        "accepted_plans_per_day": {
          "$ref": "#/$defs/metric"
        },
        "mapped_plans_per_day": {
          "$ref": "#/$defs/metric"
        },
        "accepted_held_plans_per_day": {
          "$ref": "#/$defs/metric"
        },
        "pipeline_wall_s": {
          "$ref": "#/$defs/metric"
        },
        "pipeline_bytes": {
          "$ref": "#/$defs/metric"
        },
        "local_tokens": {
          "$ref": "#/$defs/metric"
        },
        "local_latency_s": {
          "$ref": "#/$defs/metric"
        },
        "contour_visual_clean": {
          "$ref": "#/$defs/metric"
        },
        "n16_within_budget": {
          "$ref": "#/$defs/metric"
        },
        "cache_peak_bytes": {
          "$ref": "#/$defs/metric"
        },
        "token_cost": {
          "$ref": "#/$defs/metric"
        },
        "projected_coast_days": {
          "$ref": "#/$defs/metric"
        },
        "operator_rescues": {
          "$ref": "#/$defs/metric"
        },
        "broken_receipts": {
          "$ref": "#/$defs/metric"
        },
        "hash_mismatches": {
          "$ref": "#/$defs/metric"
        }
      }
    }
  },
  "$defs": {
    "metric": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "status",
        "value",
        "display",
        "reason",
        "population",
        "evidence"
      ],
      "properties": {
        "status": {
          "enum": [
            "measured",
            "not_applicable",
            "unavailable"
          ]
        },
        "value": {
          "type": [
            "number",
            "boolean",
            "null"
          ]
        },
        "display": {
          "type": "string"
        },
        "reason": {
          "type": [
            "string",
            "null"
          ]
        },
        "population": {
          "type": "object"
        },
        "evidence": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/ref"
          }
        }
      },
      "allOf": [
        {
          "if": {
            "properties": {
              "status": {
                "const": "measured"
              }
            }
          },
          "then": {
            "properties": {
              "value": {
                "type": [
                  "number",
                  "boolean"
                ]
              },
              "reason": {
                "type": "null"
              }
            }
          },
          "else": {
            "properties": {
              "value": {
                "type": "null"
              },
              "display": {
                "const": "not measured"
              },
              "reason": {
                "type": "string"
              }
            }
          }
        }
      ]
    },
    "ref": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "root_id",
        "path",
        "sha256",
        "bytes"
      ],
      "properties": {
        "root_id": {
          "type": "string"
        },
        "path": {
          "type": "string"
        },
        "sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "bytes": {
          "type": "integer",
          "minimum": 0
        }
      }
    }
  }
}
```
