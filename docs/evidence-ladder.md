# The evidence ladder

Any statement that a charter boat spent time somewhere carries one rung of a fixed ladder, with its evidence
count and the coverage caveat of its source. Code: `server/fleet/evidence-ladder.ts`.

| Rung | Needs | Count is |
| --- | --- | --- |
| `named-report` | one named report (or several from one publisher) | independent sources |
| `repeated-report` | two or more independent named reports | independent sources |
| `ais-linger` | an AIS stop the classifier kept, at or over its region threshold | lingers that met it |
| `ais-linger-verified` | the same, on a vessel the registry confirms (MMSI plus a USCG document or state registration, same MMSI on every trip) | lingers that met it |

- A rung cannot be set: only `reportClaim` and `aisClaim` build one, from their own evidence. No evidence returns no claim, never a rung with count zero.
- Reports sharing a source (a syndicated post, the daily landing feed) are one voice.
- Every rung has a caveat. AIS follows Global Fishing Watch's wording, "apparent fishing effort": small vessels are poorly covered, so absence is not evidence of absence.
- A report's place is the polygon it was reported as. No centroid, representative point, jitter or heat contribution is ever made from it; a non-area geometry on a report is dropped.
- AIS rungs are admin only (`publicClaims` in `server/fleet/display.ts`); thresholds, the registry's rules and AIS sources are unchanged.
