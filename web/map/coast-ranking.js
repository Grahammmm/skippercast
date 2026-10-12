// packages/coast's reviewed reef habitat and its ranking for the brief's "Where to
// look" (FE-34), imported dynamically by web/ranking.ts. Plain JavaScript typed by
// coast-ranking.d.ts, as coast-habitat.js: the readers sit beside the renderer
// (coast3d/regional.ts), which web/tsconfig.json never loads. Bridge reads only
// (`coastFetch`), never three. The release's own gates decide what is admitted:
// `readReviewedHabitat` checks the publication and its screen clocks, and
// `rankedHabitat` keeps exportable, screened, unexpired polygons in fit order.
import {readReviewedHabitat} from '../../packages/coast/src/map/habitat-lifecycle.ts';
export {rankedHabitat} from '../../packages/coast/src/coast3d/regional.ts';

/** The reviewed reef habitat release, and when its manifest or any region's review expires. */
export async function loadReviewedHabitat() {
  const {manifest, details} = await readReviewedHabitat('/data/skippercast-manifest.json', '/data/skippercast-habitat.geojson');
  const expiresAt = Math.min(Date.parse(manifest.expiresAt), ...manifest.regions.map(r => Date.parse(r.expiresAt)));
  return {features: details, expiresAt};
}
