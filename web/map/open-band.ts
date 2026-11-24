// RF0905-1 (phone-pass issue 5): the MapLibre padding that draws the camera centre in the middle of the open band
// between the phone's top card and its sheet. Pure: the Chart (web/map/chart.ts) passes the rects in.
export interface Box {top: number; bottom: number; left: number; right: number}

const EDGE = 8;

/**
 * A cover counts if its four numbers are finite, it overlaps `host` and spans at least half its width; one at
 * the top edge (within 8 px) pads the top, one at the bottom edge pads the bottom, one at both (a full sheet) neither.
 * Edge coverage is measured on the visible intersection with the host.
 * If needed, shrink both pads proportionally to leave at least `minBand` px; a host under `minBand` pads nothing.
 * If that shrink would carry the camera centre out of a visible gap between the covers, the centre stays on the gap midpoint instead.
 */
export function openBandPadding(host: Box, covers: readonly Box[], minBand = 160): {top: number; bottom: number; left: 0; right: 0} {
  const height = host.bottom - host.top, width = host.right - host.left;
  let top = 0, bottom = 0;
  // A host with a non-finite coordinate, or a non-finite / nonpositive size (also from overflow), defines no band.
  if (![host.top, host.bottom, host.left, host.right, height, width].every(Number.isFinite) || !(height > 0) || !(width > 0)) return {top, bottom, left: 0, right: 0};
  if (!(height >= minBand)) return {top, bottom, left: 0, right: 0};
  for (const c of covers) {
    if (![c.top, c.bottom, c.left, c.right].every(Number.isFinite)) continue;
    const visibleTop = Math.max(c.top, host.top), visibleBottom = Math.min(c.bottom, host.bottom);
    const visibleWidth = Math.min(c.right, host.right) - Math.max(c.left, host.left);
    if (visibleTop >= visibleBottom || visibleWidth <= 0 || visibleWidth < width / 2) continue;
    const atTop = visibleTop - host.top <= EDGE, atBottom = host.bottom - visibleBottom <= EDGE;
    if (atTop && !atBottom) top = Math.max(top, visibleBottom - host.top);
    else if (atBottom && !atTop) bottom = Math.max(bottom, host.bottom - visibleTop);
  }
  const clamp = (v: number): number => Math.round(Math.min(Math.max(v, 0), height));
  top = clamp(top); bottom = clamp(bottom);
  const budget = Math.max(0, Math.floor(height - minBand));
  if (top + bottom > budget) {
    const gapTop = top, gapBottom = height - bottom, gapOpen = gapBottom > gapTop;
    top = Math.round(gapTop * budget / (gapTop + bottom));
    bottom = budget - top;
    // The camera centre is (top + height - bottom) / 2. The proportional shrink above can carry it out of a visible gap (130..144 on
    // a 844 px host landed on 187, behind the sheet). Rule: then keep the centre on the unshrunk gap midpoint, which needs
    // top - bottom = gapTop - (height - gapBottom); with top + bottom = budget that gives top = (budget + that) / 2, clamped to 0..budget.
    // The open band stays at least `minBand` wide around the point the user centred on and the pads stay within budget.
    const centre = (top + height - bottom) / 2;
    if (gapOpen && !(centre > gapTop && centre < gapBottom)) {
      top = Math.min(Math.max(Math.round((budget + gapTop - (height - gapBottom)) / 2), 0), budget);
      bottom = budget - top;
    }
  }
  return {top, bottom, left: 0, right: 0};
}

/** The phone sheet is translated partly below the screen and sits on the tab bar: it covers the map from its top to `bottom`. */
export const toEdge = (r: Box, bottom: number): Box => ({top: r.top, left: r.left, right: r.right, bottom: r.bottom > r.top ? bottom : r.bottom});
