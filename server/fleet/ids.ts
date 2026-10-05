// Deterministic ids for the charter fleet registry (docs/plans/charter-fleet/design.md
// § 5). A row a re-run must hit again gets an id derived from what defines it, so
// the Python pipeline (src/skippercast/fleet/) and the Worker compute the same id
// and a second identical write lands on the same row. Every derived id is the first
// 32 lowercase hex characters of SHA-256 over the parts joined by '|' (vessels:
// 'region:creation_key'); value keys are the first 16 of SHA-256 over the canonical
// JSON of the value.
//
// Canonical JSON (shared with Python): object keys sorted by code unit, no
// whitespace, non-ASCII left as is, numbers as JavaScript prints them (an integral
// float is written without '.0': Python must pass int(x) for those). Python:
// json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False).
import {sha256} from '../advisor/ids.ts';

export type JsonValue = null | boolean | number | string | JsonValue[] | {[key: string]: JsonValue};

/** The canonical JSON text of a value (sorted keys, no whitespace). */
export function canonicalJson(value: JsonValue): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonicalJson(value[k]!)).join(',') + '}';
}

const id32 = async (...parts: string[]): Promise<string> => (await sha256(parts.join('|'))).slice(0, 32);

/** fleet_vessels.id: sha256(region:creation_key)[:32] (creation_key e.g. 'uscg:1234567'). */
export const vesselId = async (region: string, creationKey: string): Promise<string> => (await sha256(`${region}:${creationKey}`)).slice(0, 32);
/** fleet_vessel_facts.value_key: sha256(canonical value)[:16]. */
export const valueKey = async (value: JsonValue): Promise<string> => (await sha256(canonicalJson(value))).slice(0, 16);
/** fleet_vessel_facts.id: sha256(vessel_id|field|source_id|source_url|value_key)[:32]. */
export const factId = (vessel: string, field: string, sourceId: string, sourceUrl: string, key: string): Promise<string> => id32(vessel, field, sourceId, sourceUrl, key);
/** fleet_offerings.id: sha256(vessel_id|name_norm|season)[:32]; the resolver supplies name_norm and season. */
export const offeringId = (vessel: string, nameNorm: string, season: string): Promise<string> => id32(vessel, nameNorm, season);
/** fleet_departures.id: sha256(offering_id|date|departs)[:32]; departs is departs_local or ''. */
export const departureId = (offering: string, date: string, departs: string): Promise<string> => id32(offering, date, departs);
/** fleet_reviews.id: sha256(kind|fingerprint)[:32]: a repeat updates, never duplicates. */
export const reviewId = (kind: string, fingerprint: string): Promise<string> => id32(kind, fingerprint);
/** fleet_changes.id: sha256(vessel_id|kind|after_json)[:32], after_json canonical. */
export const changeId = (vessel: string, kind: string, afterJson: string): Promise<string> => id32(vessel, kind, afterJson);
