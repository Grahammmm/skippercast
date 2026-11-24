// MSK-2: G's nearshore style kit numbers as MapLibre paint. Every number comes from the generated
// web/map/nearshore-style.gen.ts (scripts/style/gen_style.py), never from this file; builders take the
// style as a parameter so a test can hand them an edited copy and see the paint follow.
//
// Erasable syntax only: tests import this file by type stripping.
import {ZOOM_OFFSET} from './engine.ts';
import {NEARSHORE_STYLE} from './nearshore-style.gen.ts';

/** The generated style, or a test copy of the same shape. */
export type NearshoreStyle = typeof NEARSHORE_STYLE;
type ZoomPairs = readonly (readonly [number, number])[];

/**
 * A kit zoom table as MapLibre paint. The kit's zooms are web-map zooms (its ground table puts z13 at 15.6 m/px, a
 * 256 px tile), as `?view=` writes them; MapLibre's 512 px zoom is ZOOM_OFFSET less. One pair is a constant.
 */
export function kitZoom(pairs: ZoomPairs): number | unknown[] {
  if (!pairs.length) throw new Error('Nearshore zoom table needs at least one stop');
  const stops: number[] = [];
  let previous = -Infinity;
  for (const [i, pair] of pairs.entries()) {
    if (!pair || !Number.isFinite(pair[0]) || !Number.isFinite(pair[1])) {
      throw new Error(`Nearshore zoom stop ${i + 1}: zoom and value must be finite numbers`);
    }
    const [zoom, value] = pair;
    // Check the emitted coordinates: the offset can round distinct inputs to the same zoom.
    const mapZoom = zoom - ZOOM_OFFSET;
    if (mapZoom <= previous) {
      throw new Error(`Nearshore zoom stop ${i + 1}: zooms must be strictly increasing after the zoom offset`);
    }
    stops.push(mapZoom, value);
    previous = mapZoom;
  }
  return pairs.length === 1 ? stops[1]! : ['interpolate', ['linear'], ['zoom'], ...stops];
}

/** A kit web-map zoom as a MapLibre layer zoom. */
export const kitMinZoom = (zoom: number): number => zoom - ZOOM_OFFSET;

/** The opacity of a coarse colour field (water temperature, chlorophyll, swell) by zoom: strong offshore, faint close in. */
export const fieldOpacity = (style: NearshoreStyle = NEARSHORE_STYLE) => kitZoom(style.overlays.field_opacity_by_zoom);

/** The base relief's raster saturation while a colour field is on (the field carries the colour; the relief keeps its shape). */
export const fieldDesaturation = (style: NearshoreStyle = NEARSHORE_STYLE): number => -style.overlays.base_desaturation_when_field_on;
