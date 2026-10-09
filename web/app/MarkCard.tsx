// Selected-mark card (FE-05, design § 9): one card for whatever is selected,
// with name, kind, reading, source and age, the regulations line, the action
// row and a basis link. FE-11 filled it from the Chart (a clicked shoreline
// segment); FE-18 adds the atlas reef marks (`?spot=`, in every presentation),
// survey habitat and geology outlines, and the terrain's habitat (`?habitat=`)
// with the renderer's own evidence lines, or restored without graphics, while
// the Chart shows (in 2D and 3D the renderer's panel speaks for its own
// selection until FE-80 moves that panel here). A mark that names its rules
// page (a protected area, FE-19; an atlas mark or outline, FE-18) links that
// official page; the card never states the rules itself. A pick moves focus to
// the card's heading; the close button, or Escape with no basis open, clears
// the selection and returns focus to where it was (the chart, after a click).
import {computed} from '@preact/signals';
import {useEffect, useRef} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Icon} from '../ui/icons.tsx';
import {Popover} from '../ui/Popover.tsx';
import {chartMark} from '../map/chart.ts';
import type {ChartMark} from '../map/coastline.ts';
import {habitatCard, picked, spotCard} from '../map/marks.ts';
import {shownPresentation, terrainDetail, terrainMark} from '../map/stage.ts';
import {navigate, selection, setParams} from '../state.ts';

export type Mark = ChartMark;
export {terrainCard} from '../map/habitat.ts';

/** The card's placeholder while the region's marks load. */
export const placeholderMark = (id: string): Mark => ({id, name: id, kind: 'Mark', reading: '—', source: 'Source —', basis: 'The mark loads with the map engine; its source and age show here.'});

/**
 * What the card shows: on the Chart, its own selection, then the terrain's; in
 * 2D and 3D the renderer's panel speaks for the terrain's. The link's atlas mark
 * shows in every presentation.
 */
export const currentMark = computed<Mark | null>(() => {
  const chart = shownPresentation.value === 'chart', spot = spotCard.value;
  return (chart ? chartMark.value ?? habitatCard.value : null) ?? (spot === undefined ? placeholderMark(selection.value!) : spot);
});

/** Drop the selection from the address (?spot= and ?focus= are read, never written, by the store). */
export function clearSelection(href: string): string {
  const url = new URL(href);
  url.searchParams.delete('spot'); url.searchParams.delete('focus');
  return url.href;
}

/** Clear whichever selection the card shows. */
function clearMark(mark: Mark): void {
  if (mark === chartMark.peek()) { chartMark.value = null; return; }
  if (mark.id.startsWith('habitat:')) {
    // The stage then tells the renderer (selectHabitat(null)), as the scene's own close button does.
    terrainMark.value = null; terrainDetail.value = null;
    setParams({habitat: null});
    return;
  }
  navigate(clearSelection(location.href), {replace: true});
}

/** The last pick the card answered with focus, and where focus was before it. */
let answered = 0, returnTo: HTMLElement | null = null;

export function MarkCard({mark}: {mark?: Mark} = {}) {
  const selected = mark ?? currentMark.value, request = picked.value;
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // A pick, never a link or a restore, moves focus to the card so its reading is announced.
    if (!selected || request === answered || !heading.current) return;
    answered = request;
    const active = document.activeElement;
    returnTo = active instanceof HTMLElement && active !== document.body ? active : null;
    heading.current.focus();
  }, [request, selected?.id]);
  if (!selected) return null;
  const close = () => {
    const back = returnTo?.isConnected ? returnTo : document.querySelector<HTMLElement>('.app-chart canvas');
    returnTo = null;
    clearMark(selected);
    back?.focus();
  };
  return (
    <section class="app-mark" aria-label="Selected mark"
      onKeyDown={event => { if (event.key === 'Escape' && !event.currentTarget.querySelector('details[open]')) { event.preventDefault(); close(); } }}>
      <div class="app-mark-head">
        <h2 tabIndex={-1} ref={heading}>{selected.name}</h2>
        <IconButton icon="close" label="Clear selection" size="sm" onClick={close} />
      </div>
      <p class="app-mark-kind">{selected.kind}</p>
      <p class="ui-reading">{selected.reading}</p>
      <p class="app-mark-source ui-mono">{selected.source}</p>
      {selected.rules ? <p class="app-mark-rules">{selected.rules}</p> : null}
      <div class="app-mark-actions">
        <Button size="sm" icon="plus" disabled>Add to trip</Button>
        <Button size="sm" icon="download" disabled>GPX</Button>
        {selected.regulations ? (
          <a class="ui-button ui-button--ghost ui-button--sm" href={selected.regulations.href} target="_blank" rel="noopener"
            aria-label={`Regulations: ${selected.regulations.label} (official page, opens in a new tab)`}>
            <Icon name="shield" size={16} />Regulations
          </a>
        ) : <Button size="sm" icon="shield" disabled>Regulations</Button>}
      </div>
      <Popover>{selected.basis}</Popover>
    </section>
  );
}
