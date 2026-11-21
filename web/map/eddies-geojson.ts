import type {Eddy} from './eddies-feed.ts';

type Position = Eddy['outline'][number];
type Feature = {type: 'Feature'} & (
  | {
    geometry: {type: 'Polygon'; coordinates: [Position[]]};
    properties: {kind: 'eddy'; index: number; sense: Eddy['sense']; diameter_km: number; frame_time: string};
  }
  | {
    geometry: {type: 'Point'; coordinates: Position};
    properties: {kind: 'eddy-sense'; index: number; sense: Eddy['sense']; bearing: 90 | 270};
  }
);

export function eddiesGeoJSON(tile: {frameTime: string; eddies: readonly Eddy[]}): {
  type: 'FeatureCollection'; features: Feature[];
} {
  const outlines: Feature[] = [];
  const arrows: Feature[] = [];
  tile.eddies.forEach(({outline, sense, diameterKm}, index) => {
    // An empty direct input has neither an outline nor a vertex for an arrow.
    if (outline.length === 0) return;
    // Parsed outlines have at least four positions. Also close open rings supplied directly.
    const ring = outline.map(([lon, lat]): Position => [lon, lat]);
    const first = ring[0]!, last = ring[ring.length - 1]!;
    let north = first;
    for (const point of ring) {
      if (point[1] > north[1] || (point[1] === north[1] && point[0] < north[0])) north = point;
    }
    if (first[0] !== last[0] || first[1] !== last[1]) ring.push([...first]);

    outlines.push({
      type: 'Feature',
      geometry: {type: 'Polygon', coordinates: [ring]},
      properties: {
        kind: 'eddy', index, sense,
        // Whole kilometres need no rounding; scaling large integers could overflow.
        diameter_km: Number.isInteger(diameterKm) ? diameterKm : Math.round(diameterKm * 10) / 10,
        frame_time: tile.frameTime,
      },
    });
    arrows.push({
      type: 'Feature',
      geometry: {type: 'Point', coordinates: [...north]},
      properties: {kind: 'eddy-sense', index, sense, bearing: sense === 'cw' ? 90 : 270},
    });
  });
  return {type: 'FeatureCollection', features: outlines.concat(arrows)};
}
