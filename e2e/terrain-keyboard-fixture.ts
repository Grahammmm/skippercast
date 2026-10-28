// A tiny, clearly synthetic coast-wide terrain for the 3D keyboard case (#422 terrain-keyboard cycle).
// The renderer's held dataset fetch aborts after its real 20 s timeout (packages/coast/src/coast3d/viewer.ts),
// so a test that keeps every coast request held loses the terrain mid-sequence. This fixture answers only the
// manifest and its one overview asset, and only when the test releases them; every other coast request stays
// held as before. Nothing here is survey or provider data.
import {createHash} from 'node:crypto';
import type {Page, Route} from '@playwright/test';

/** 2×2 grid: four float32 heights (metres, below the water reference) then four source ids. */
const SIZE = 2;
export const OVERVIEW: Buffer = (() => {
  const out = Buffer.alloc(SIZE * SIZE * 5);
  [-12, -10, -8, -6].forEach((v, i) => out.writeFloatLE(v, i * 4));
  out.fill(1, SIZE * SIZE * 4);
  return out;
})();
const OVERVIEW_URL = '/data/coast-wide/synthetic-keyboard-overview.bin';

/** The viewer's manifest contract (RegionalManifest): origin pinned, one synthetic source, no tiles or imagery. */
export const MANIFEST = Object.freeze({
  schemaVersion: 1,
  origin: [-120.98, 35.43],
  bounds: [0, 0, 4096, 4096],
  waterReferenceM: 0,
  sources: [{id: 1, label: 'Synthetic test terrain (not survey data)', kind: 'model', resolutionM: null, datum: 'synthetic',
    sourceDate: '2026-10-18', url: 'https://example.org/synthetic-test-terrain'}],
  overview: {url: OVERVIEW_URL, sha256: createHash('sha256').update(OVERVIEW).digest('hex'), bytes: OVERVIEW.length,
    size: SIZE, x: 0, z: 0, dx: 4096, dz: 4096},
  tiles: [], harborTiles: [], imagery: [],
});

/**
 * Route the manifest and the overview into a hold the test controls. Register after `holdCoastData` (later routes
 * win). `release()` answers both once; until then they are held exactly like every other coast request.
 */
export async function syntheticTerrain(page: Page): Promise<{release(): void}> {
  let released = false;
  const waiting: (() => void)[] = [];
  const hold = (answer: (route: Route) => Promise<void>) => (route: Route) => {
    if (released) return answer(route);
    waiting.push(() => { void answer(route); });
  };
  await page.route('**/coast-data/data/coast-wide/manifest.json', hold(route => route.fulfill({json: MANIFEST})));
  await page.route(`**/coast-data${OVERVIEW_URL}`, hold(route => route.fulfill({body: OVERVIEW, contentType: 'application/octet-stream'})));
  return {release() { released = true; for (const answer of waiting.splice(0)) answer(); }};
}
