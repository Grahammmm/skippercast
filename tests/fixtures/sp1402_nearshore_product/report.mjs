// Synthetic producer shape from tests/test_nearshore_layer.mjs, not source data.
export const NOW = new Date('2026-10-09T18:00:00Z');
export const AT = new Date('2026-10-09T20:00:00Z');
export const TZ = 'America/Los_Angeles';
export const HOUR = 3_600_000;
export const iso = ms => new Date(ms).toISOString();
export function site(patch = {}) {
  return {id: 'synthetic-a', name: 'Synthetic Alpha', areaId: 'central', lat: 35.25, lon: -120.75, sourceId: 'cdip-mop',
    issuedAt: iso(NOW - 6 * HOUR), fetchedAt: iso(NOW - HOUR), url: 'https://example.test/model-a',
    kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 60,
    waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: null,
    hours: Array.from({length: 25}, (_, k) => ({at: iso(Date.parse('2026-10-09T12:00:00Z') + k * HOUR),
      waveFt: 3 + k * 0.1, periodS: 13, directionDeg: 290, qualityFlag: 0, secondaryFlag: 0})), ...patch};
}
export const source = (id, label, url = 'https://example.test/model-a') =>
  ({id, label, url, kind: 'forecast', outcome: 'ok', fetchedAt: iso(NOW - HOUR)});
export const CDIP = source('cdip-mop', 'CDIP MOP · nearshore wave model');
export const OTHER = source('other-model', 'Synthetic Other · nearshore wave model', 'https://example.test/model-b');
export const sites = () => [site(), site({id: 'synthetic-b', name: 'Synthetic Beta', lat: 35.4, lon: -120.9,
  sourceId: 'other-model', url: 'https://example.test/model-b'})];
export function report(nearshore = sites(), sources = [CDIP, OTHER]) {
  return {schemaVersion: 1, countyId: 'slo', generatedAt: iso(NOW - HOUR), forecasts: [], observations: [], tides: [],
    tideEvents: [], alerts: [], sources, catches: [], catchStatus: '', habitatStatus: '',
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, nearshore};
}
