import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: ['https://skippercast.com']};
const {coastFeeds, serveCoastData} = await import('../server/coast-data.ts');

// FE87 / COVER-04: synthetic rights register; no provider data or requests.
const dependencies = {
  report: ['nws-weather', 'ndbc-buoys', 'noaa-tides', 'landing-reports', 'noaa-blended-sst', 'cdfw-mpas'],
  nearshore: ['cdip-mop'],
  'water-quality': ['slo-beach-water-quality'],
  ocean: ['noaa-wcofs', 'noaa-hfr-thredds', 'noaa-goes-nowcoast'],
  history: ['ndbc-history'],
};
const names = Object.keys(dependencies);
const approved = Object.values(dependencies).flat().map(id => Object.freeze({
  id, review_status: 'approved', rights: Object.freeze({commercial_use: 'allowed'}),
}));
Object.freeze(approved);
const unavailable = id => approved.map(row => row.id === id ? {...row, review_status: 'unavailable'} : row);
const request = path => new Request('https://skippercast.com/api/coast/' + path);
// FE-62: the Worker reads no other origin, so any outbound request is a failure.
let outbound = 0;
globalThis.fetch = async () => { outbound++; throw Error('Must not fetch another origin'); };
const sorted = feeds => [...feeds].sort();

test('approved synthetic source controls admit every requested coast feed', () => {
  assert.deepEqual(sorted(coastFeeds(approved)), sorted(names));
});

for (const [feed, sources] of Object.entries(dependencies)) {
  for (const id of sources) {
    test(`unavailable ${id} excludes only its dependent ${feed} feed`, async () => {
      const catalog = unavailable(id), before = structuredClone(catalog);
      const admitted = coastFeeds(catalog);
      assert.deepEqual(sorted(admitted), sorted(names.filter(name => name !== feed)));
      assert.deepEqual(catalog, before, 'admission must not mutate source review state');

      // Request the refused feed alone so unrelated report enrichment cannot
      // mask an accidental read. Even an attempted head/get must be recorded:
      // ownFeed catches store errors, so throwing alone would be a weak oracle.
      const reads = [];
      const store = {
        async head(key) { reads.push(key); throw Error('Refused feed read'); },
        async get(key) { reads.push(key); throw Error('Refused feed read'); },
      };
      const calls = outbound;
      const path = ['nearshore', 'water-quality'].includes(feed) ? 'report' : feed;
      const alone = new Set([...admitted].filter(name => name === feed));
      const response = await serveCoastData(request(path), store, alone);
      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), {error: 'Coast source unavailable'});
      assert.ok(response.headers.get('X-Coast-Upstream').includes(`${feed}=unavailable (refused)`));
      assert.equal(outbound, calls, 'a refused feed is not filled from another origin');
      assert.deepEqual(reads, [], 'unavailable source flags must prevent own-feed reads');
    });
  }
}

test('an approved ocean control reads and serves its own synthetic feed', async () => {
  const generatedAt = new Date().toISOString();
  const ocean = {schemaVersion: 1, countyId: 'slo', generatedAt, currents: [], cloud: null,
    sources: [{id: 'synthetic-ocean', status: 'ok', fetchedAt: generatedAt}]};
  const bytes = new TextEncoder().encode(JSON.stringify(ocean)), reads = [];
  const store = {
    async get(key) {
      reads.push(key);
      return {size: bytes.byteLength, arrayBuffer: async () => bytes.buffer};
    },
  };
  const before = outbound;
  const response = await serveCoastData(request('ocean'), store, coastFeeds(approved));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), ocean);
  assert.equal(response.headers.get('X-Coast-Upstream'), 'ocean=skippercast');
  assert.equal(outbound, before);
  assert.deepEqual(reads, ['conditions/regions/morro-bay/coast-ocean.json']);
});
