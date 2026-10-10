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
// FE-51: an atlas mark's "Add to trip" and "GPX" go to the trip planner
// (web/trip.ts), as v1's spot sheet does; a ranked trip spot's pin (#495) opens
// it in the plan with v1's "Review & export"; other selections have no trip action.
// FE-82: in 2D and 3D a protected area or charter ground picked on the terrain
// (stage.ts `terrainPick`) gets the card the Chart's click gives it; a reef mark
// picked there selects `?spot=`, as on the Chart.
import {computed} from '@preact/signals';
import {useEffect, useRef} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Icon} from '../ui/icons.tsx';
import {Popover} from '../ui/Popover.tsx';
import {chartMark} from '../map/chart.ts';
import type {ChartMark} from '../map/coastline.ts';
import {habitatCard, markData, picked, spotCard} from '../map/marks.ts';
import {shownPresentation, terrainDetail, terrainMark, terrainPick} from '../map/stage.ts';
import {navigate, selection, setParams} from '../state.ts';
import {addToTrip, reviewTrip, tripIds} from '../trip.ts';

export type Mark = ChartMark;
export {terrainCard} from '../map/habitat.ts';

/** The card's placeholder while the region's marks load. */
export const placeholderMark = (id: string): Mark => ({id, name: id, kind: 'Mark', reading: '—', source: 'Source —', basis: 'The mark loads with the map engine; its source and age show here.'});

/**
 * What the card shows: on the Chart, its own selection, then the terrain's; in
 * 2D and 3D an overlay picked on the terrain, while the renderer's panel speaks
 * for its own habitat selection. The link's atlas mark shows in every presentation.
 */
export const currentMark = computed<Mark | null>(() => {
  const chart = shownPresentation.value === 'chart', spot = spotCard.value;
  return (chart ? chartMark.value ?? habitatCard.value : terrainPick.value) ?? (spot === undefined ? placeholderMark(selection.value!) : spot);
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
  if (mark === terrainPick.peek()) { terrainPick.value = null; return; }
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
  // Only an atlas mark or a ranked spot joins a trip: v1's planner exports those. A mark the run-time screen withholds (#489) never does.
  const spot = selected === spotCard.value && !selected.withheld ? selection.value : selected.trip ?? null;
  const target = spot ? markData.value?.atlas?.targets.find(t => t.id === spot) as {canonical_habitat?: boolean} | undefined : undefined;
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
      {selected.rules ? (
        <p class="app-mark-rules">{selected.rules}{selected.regulations ? <>{' '}
          <a href={selected.regulations.href} target="_blank" rel="noopener" aria-label={`${selected.regulations.label} (official page, opens in a new tab)`}>{selected.regulations.label}</a>
        </> : null}</p>
      ) : null}
      <div class="app-mark-actions">
        <Button size="sm" icon={spot && tripIds.value.includes(spot) ? 'check' : 'plus'} disabled={!spot} onClick={() => { if (spot) void addToTrip(spot); }}>
          {spot && tripIds.value.includes(spot) ? 'Added to trip' : target && target.canonical_habitat !== true ? 'Save research reference' : 'Add to trip'}</Button>
        <Button size="sm" icon="download" disabled={!spot} onClick={() => { if (spot) void reviewTrip(spot); }}>{selected.trip ? 'Review & export' : 'GPX'}</Button>
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
