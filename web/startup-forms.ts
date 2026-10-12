// Light startup copies of a region's map files (#617): the platform build
// (src/skippercast/platform/startup_forms.py) writes each beside the region
// package, and the map reads the copy at startup, falling back to the full
// file when the copy is missing. The shoreline's overview form is in
// web/map/coastline.ts. Erasable syntax only: tests import it by type stripping.

/** The atlas without its habitat area and drift geometry: what the marks, the ranking and the mark card read. */
export const atlasMarksURL = (region: string): string => `regions/${encodeURIComponent(region)}/atlas-marks.json`;
/** Each species plan's profile entry without the plans' feature geometry: what the target list reads. */
export const planIndexURL = (region: string): string => `regions/${encodeURIComponent(region)}/search-plan-index.json`;
