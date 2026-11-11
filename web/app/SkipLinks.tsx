// Skip links (SC1722-20, UX audit S4-11): the first two tab stops on /map. "Skip to brief" moves focus into the brief,
// "Skip to map" to the map canvas, so a keyboard user does not tab through the masthead and command bar first. Both are real
// anchors, clipped to a pixel until focused (web/app/app.css), and a handled activation never changes the address.
import {useEffect, useRef} from 'preact/hooks';
import {mapFocusTarget} from './map-focus.ts';
import {appView, setParams, type AppView} from '../state.ts';
import {language, t} from '../i18n.ts';

export const BRIEF_ID = 'app-brief-content';
export const MAP_ID = 'app-map-content';
export type SkipTarget = 'brief' | 'map';

/** Whether `view` hides the target (so the Coast view must be shown first): the Fleet view replaces the desktop brief, the Reports and Plan pages cover it, and every phone view takes the sheet's place; any other view covers the map. */
export function needsCoast(target: SkipTarget, view: AppView, phone: boolean): boolean {
  if (view === 'coast') return false;
  if (target === 'map') return true;
  return phone || view === 'fleet' || view === 'reports' || view === 'plan';
}

/** The element focus goes to: the brief's own root, or the visible map canvas (its host, or the stage when no canvas can exist). */
export function skipFocusTarget(doc: Document, target: SkipTarget): HTMLElement | null {
  if (target === 'brief') return doc.getElementById(BRIEF_ID);
  const el = mapFocusTarget(doc);
  if (!el) return null;
  // A canvas made by the map library may not be focusable from script: give just this one tabindex -1, never a positive tab order.
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  return el;
}

/** Focus the target; the map falls back to its stage when the canvas will not take focus. A missing target is a no-op. */
export function focusSkipTarget(doc: Document, target: SkipTarget): boolean {
  const el = skipFocusTarget(doc, target);
  if (!el) return false;
  el.focus({preventScroll: true});
  if (doc.activeElement === el) return true;
  const stage = target === 'map' ? doc.getElementById(MAP_ID) : null;
  stage?.focus({preventScroll: true});
  return !!stage && doc.activeElement === stage;
}

export function SkipLinks({phone = false, prepare}: {phone?: boolean; prepare?: (target: SkipTarget) => void}) {
  const lang = language.value, pending = useRef(0);
  useEffect(() => () => cancelAnimationFrame(pending.current), []);
  const go = (target: SkipTarget) => (event: MouseEvent) => {
    event.preventDefault();
    const from = document.activeElement;
    if (needsCoast(target, appView.peek(), phone)) setParams({view: null});
    prepare?.(target);
    // One frame after Preact commits the state above; focus moves only if the user has not gone somewhere else meanwhile.
    cancelAnimationFrame(pending.current);
    pending.current = requestAnimationFrame(() => {
      pending.current = 0;
      const now = document.activeElement;
      if (now && now !== from && now !== document.body) return;
      focusSkipTarget(document, target);
    });
  };
  return (
    <>
      <a class="app-skip-link" href={`#${BRIEF_ID}`} onClick={go('brief')}>{t('a11y.skip.brief', lang)}</a>
      <a class="app-skip-link" href={`#${MAP_ID}`} onClick={go('map')}>{t('a11y.skip.map', lang)}</a>
    </>
  );
}
