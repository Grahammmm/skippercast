// Synthetic SLO report and buoy history for the /coast report dialog (FE-77):
// never a forecast, observation, catch count or production feed. Every clock is
// relative to `now`, which the spec also fixes in the browser, so the dialog
// renders the same markup on every run.
const HOUR = 3_600_000;

export function coastReportFixture(now: number) {
  const start = Math.floor(now / HOUR) * HOUR, at = (h: number) => new Date(start + h * HOUR).toISOString(), iso = new Date(now).toISOString();
  const day = iso.slice(0, 10);
  const hours = Array.from({length: 72}, (_, i) => ({at: at(i - 6), windKnots: 6 + (i % 9), gustKnots: 9 + (i % 11), waveFt: 2.5 + (i % 5) / 4,
    wavePeriodS: 11, swellFt: 2, swellPeriodS: 12, windWaveFt: .5, windDirectionDeg: 300, airTempF: 61, precipPct: 5, cloudCoverPct: 30, daylight: (i % 24) > 6 && (i % 24) < 19}));
  const tides = Array.from({length: 72 * 10}, (_, i) => ({at: new Date(start - 6 * HOUR + i * 6 * 60000).toISOString(), heightFt: 2.5 + 2 * Math.sin(i / 62)}));
  const source = (id: string, label: string, kind: string) => ({id, label, url: 'https://example.com/' + id, kind, outcome: 'ok', fetchedAt: iso, issuedAt: iso});
  return {
    schemaVersion: 1, countyId: 'slo', generatedAt: iso,
    forecasts: ['north', 'central', 'south'].map(id => ({id, sourceId: 'nws-' + id, issuedAt: iso, hours})),
    sources: [source('nws-north', 'NWS north', 'forecast'), source('nws-central', 'NWS central', 'forecast'), source('nws-south', 'NWS south', 'forecast'),
      source('nws-alerts', 'Alerts', 'forecast'), source('noaa-tides', 'Tides', 'prediction'), source('ndbc', 'Buoys', 'observation')],
    observations: [{stationId: '46215', observedAt: iso, url: 'https://example.com/46215', waterTempF: 57.4, windKnots: 8, gustKnots: 11, waveFt: 3.1, wavePeriodS: 12, directionDeg: 300},
      {stationId: '46011', observedAt: iso, url: 'https://example.com/46011', waterTempF: 56.1, windKnots: 12, gustKnots: 15, waveFt: 4.2, wavePeriodS: 11, directionDeg: 310}],
    tides, tideEvents: [{at: at(2), heightFt: 4.4, type: 'H'}, {at: at(8), heightFt: .6, type: 'L'}, {at: at(14), heightFt: 3.9, type: 'H'}, {at: at(20), heightFt: 1.1, type: 'L'}],
    alerts: [],
    catches: [{id: 'trip-1', tripDate: day, boat: 'Fixture vessel', landing: 'Fixture landing', anglers: 12, tripType: '3/4 Day',
      species: [{name: 'Rockfish', count: 120, disposition: 'reported'}, {name: 'Lingcod', count: 9, disposition: 'reported'}], sourceUrl: 'https://example.com/trip-1', retrievedAt: iso},
    {id: 'trip-2', tripDate: day, boat: 'Second fixture vessel', landing: 'Fixture landing', anglers: 8, tripType: 'Full Day',
      species: [{name: 'Rockfish', count: 80, disposition: 'reported'}], sourceUrl: 'https://example.com/trip-2', retrievedAt: iso}],
    catchContext: {feedUrl: 'https://example.com/feed', feedGeneratedAt: iso, receivedAt: iso, windowStart: day, windowEnd: day, latestTripDate: day,
      rights: {scope: 'linked-factual-counts', reviewedAt: iso, sourceCatalogUrl: 'https://example.com/rights'}},
    catchStatus: 'Linked facts', visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: 'Pending',
  };
}

export function coastHistoryFixture(now: number) {
  const start = Math.floor(now / HOUR) * HOUR, iso = new Date(now).toISOString(), keys = ['waterTempF', 'airTempF', 'windKnots', 'gustKnots', 'waveFt', 'periodS'] as const;
  const hours = Array.from({length: 45 * 24}, (_, i) => ({at: new Date(start - (45 * 24 - 1 - i) * HOUR).toISOString(), waterTempF: 56 + Math.sin(i / 40), airTempF: 60,
    windKnots: 8 + (i % 7), gustKnots: 11 + (i % 7), waveFt: 3 + Math.sin(i / 30), periodS: 11, sampleCount: 1, counts: Object.fromEntries(keys.map(k => [k, 1]))}));
  return {schemaVersion: 1, countyId: 'slo', generatedAt: iso, recentWindowDays: 45, stations: [{stationId: '46215', name: 'Fixture buoy', lat: 35.2, lon: -120.86,
    recent: {from: hours[0]!.at, through: iso, firstObservedAt: hours[0]!.at, lastObservedAt: hours.at(-1)!.at, stale: false, expectedHours: hours.length, observedHours: hours.length,
      hourCoverageFraction: 1, maxGapHours: 1, hours, qc: {inputRows: hours.length, acceptedRows: hours.length, rejectedRows: 0, duplicateRows: 0, conflictingValues: 0, maskedValues: 0, trailingMissingRows: 0}},
    baseline: {kind: 'unavailable', label: 'Unavailable', years: [], periodStart: null, periodEnd: null, aggregation: 'UTC-hour means, weighted equally', months: []},
    archive: {indexUrl: 'https://example.com/index', availableYears: [], discoveredAt: iso, outcome: 'ok'},
    sources: [{url: 'https://example.com/recent', role: 'recent', outcome: 'ok', fetchedAt: iso}], limitations: []}]};
}
