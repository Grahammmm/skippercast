// RF0905-1 (phone-pass issue 5): the MapLibre padding that draws the camera centre in the middle of the open band
// between the phone's top card and its sheet. Pure: the Chart (web/map/chart.ts) passes the rects in.
export interface Box {top: number; bottom: number; left: number; right: number}

const EDGE = 8;

/**
 * A cover counts if its four numbers are finite, it overlaps `host` and spans at least half its width; one at
 * the top edge (within 8 px) pads the top, one at the bottom edge pads the bottom, one at both (a full sheet) neither.
 * A band under `minBand` px shrinks both in proportion to exactly `minBand`; a host under `minBand` pads nothing.
 */
export function openBandPadding(host: Box, covers: readonly Box[], minBand = 160): {top: number; bottom: number; left: 0; right: 0} {
  const height = host.bottom - host.top, width = host.right - host.left;
  let top = 0, bottom = 0;
  if (!(height >= minBand)) return {top, bottom, left: 0, right: 0};
  for (const c of covers) {
    if (![c.top, c.bottom, c.left, c.right].every(Number.isFinite)) continue;
    if (c.bottom <= host.top || c.top >= host.bottom || c.right <= host.left || c.left >= host.right) continue;
    if (Math.min(c.right, host.right) - Math.max(c.left, host.left) < width / 2) continue;
    const atTop = Math.abs(c.top - host.top) <= EDGE, atBottom = Math.abs(c.bottom - host.bottom) <= EDGE;
    if (atTop && !atBottom) top = Math.max(top, c.bottom - host.top);
    else if (atBottom && !atTop) bottom = Math.max(bottom, host.bottom - c.top);
  }
  const clamp = (v: number): number => Math.round(Math.min(Math.max(v, 0), height));
  top = clamp(top); bottom = clamp(bottom);
  if (height - top - bottom < minBand) {
    top = Math.round(top * (height - minBand) / (top + bottom));
    bottom = Math.round(height - minBand - top);
  }
  return {top, bottom, left: 0, right: 0};
}
