// Where focus returns when the mark card closes and the element that had it is gone (SC2222-04): the map
// the user is looking at, never <body>. A canvas under a `hidden` ancestor (the Chart in 2D/3D, or after the
// Chart failed) cannot take focus, so it is skipped; the terrain's canvas lives in a shadow root, so its
// host stands in; the stage itself is the last resort.
const CANDIDATES = ['.app-chart canvas', '.app-terrain canvas', '.app-terrain'];

export function mapFocusTarget(doc: ParentNode): HTMLElement | null {
  for (const selector of CANDIDATES) {
    const el = doc.querySelector<HTMLElement>(selector);
    if (el && !el.closest('[hidden]')) return el;
  }
  return doc.querySelector<HTMLElement>('.app-stage');
}
