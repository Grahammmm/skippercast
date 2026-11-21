import {chlEdgesShown, type ChlEdgesDoc} from './chl-edges-feed.ts';

// Same zoom-0 Web Mercator scale as the SST fronts in fronts.ts.
const METRES_PER_PIXEL_Z0 = 78271.517;

export type ChlEdgeFeature = {type: 'Feature'; properties: {id: string; px0: number; strength: number}; geometry: {type: 'LineString'; coordinates: number[][]}};

/** Project each parsed edge with its full band width in pixels at zoom 0. */
export function chlEdgeFeatures(doc: Pick<ChlEdgesDoc, 'edges'>): {type: 'FeatureCollection'; features: ChlEdgeFeature[]} {
  return {type: 'FeatureCollection', features: doc.edges.map(({id, line, bandHalfWidthKm, strength}) => {
    const meanLat = line.reduce((sum, [, lat]) => sum + lat, 0) / line.length;
    const metresPerPixel = METRES_PER_PIXEL_Z0 * Math.max(Math.cos(meanLat * Math.PI / 180), 1e-6);
    const px0 = Number((2 * bandHalfWidthKm * 1000 / metresPerPixel).toFixed(8));
    return {type: 'Feature', properties: {id, px0, strength}, geometry: {type: 'LineString', coordinates: line.map(([lon, lat]) => [lon, lat])}};
  })};
}

type HiddenReason = Extract<ReturnType<typeof chlEdgesShown>, {show: false}>['reason'];

/** Gate drawing on the parsed feed's display eligibility. */
export function chlEdgesDraw(doc: ChlEdgesDoc, now: Date):
  {draw: true; data: ReturnType<typeof chlEdgeFeatures>} | {draw: false; reason: HiddenReason} {
  const shown = chlEdgesShown(doc, now);
  return shown.show ? {draw: true, data: chlEdgeFeatures(doc)} : {draw: false, reason: shown.reason};
}
