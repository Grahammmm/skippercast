// When the mark card's previous focus is gone, return to the map the user is looking at.
// A render transition can leave earlier canvases mounted but unusable. Prefer the Chart,
// then terrain (its shadow host if the canvas is not reachable), with the stage last.
const CANDIDATES = ['.app-chart canvas', '.app-terrain canvas', '.app-terrain', '.app-stage'];

export function mapFocusTarget(doc: ParentNode): HTMLElement | null {
  for (const selector of CANDIDATES) {
    for (const el of doc.querySelectorAll<HTMLElement>(selector)) {
      if (!el.closest('[hidden], [inert]') && el.getClientRects().length &&
          el.ownerDocument.defaultView?.getComputedStyle(el).visibility === 'visible') return el;
    }
  }
  return null;
}
