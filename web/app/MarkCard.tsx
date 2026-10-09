// Selected-mark card (FE-05, design § 9): one card for whatever is selected,
// with name, kind, reading, source and age, the action row and a basis link.
// FE-11 fills it from the Chart (a clicked shoreline segment, web/map/chart.ts)
// and, while the Chart shows, from the terrain's admitted habitat selection
// (in 2D and 3D the renderer's own panel shows it). An atlas `?spot=` or
// `?focus=` keeps its placeholder until FE-18 draws the marks.
import {computed} from '@preact/signals';
import type {CoastSelection} from '../../packages/coast/src/embed-types.ts';
import {Button, IconButton} from '../ui/Button.tsx';
import {Popover} from '../ui/Popover.tsx';
import {chartMark} from '../map/chart.ts';
import type {ChartMark} from '../map/coastline.ts';
import {shownPresentation, terrainMark} from '../map/stage.ts';
import {navigate, selection, setParams} from '../state.ts';

export type Mark = ChartMark;

/** The card's placeholder for a selection the engine has not resolved. */
export const placeholderMark = (id: string): Mark => ({id, name: id, kind: 'Mark', reading: '—', source: 'Source —', basis: 'The mark loads with the map engine; its source and age show here.'});

const degrees = (value: number, positive: string, negative: string): string => `${Math.abs(value).toFixed(4)}° ${value >= 0 ? positive : negative}`;
/** The terrain's habitat selection as a card: its id and position; its evidence lines stay in the terrain. */
export const terrainCard = (s: CoastSelection): Mark => ({
  id: `habitat:${s.id ?? ''}`, name: 'Selected habitat', kind: s.id ? `Terrain habitat · ${s.id}` : 'Terrain habitat',
  reading: `${degrees(s.latitude, 'N', 'S')}, ${degrees(s.longitude, 'E', 'W')}`, source: 'Coastal terrain selection',
  basis: 'Chosen in the 2D or 3D terrain, where its evidence and source lines show.',
});

/**
 * What the card shows: on the Chart, its own selection, then the terrain's; in 2D and 3D the
 * renderer's panel speaks for both. The link's atlas mark shows in every presentation.
 */
export const currentMark = computed<Mark | null>(() => {
  const chart = shownPresentation.value === 'chart', picked = terrainMark.value;
  return (chart ? chartMark.value ?? (picked ? terrainCard(picked) : null) : null) ?? (selection.value ? placeholderMark(selection.value) : null);
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
  if (mark.id.startsWith('habitat:') && terrainMark.peek()) {
    // The stage then tells the renderer (selectHabitat(null)), as the scene's own close button does.
    terrainMark.value = null;
    setParams({habitat: null});
    return;
  }
  navigate(clearSelection(location.href), {replace: true});
}

export function MarkCard({mark}: {mark?: Mark} = {}) {
  const selected = mark ?? currentMark.value;
  if (!selected) return null;
  return (
    <section class="app-mark" aria-label="Selected mark">
      <div class="app-mark-head">
        <h2>{selected.name}</h2>
        <IconButton icon="close" label="Clear selection" size="sm" onClick={() => clearMark(selected)} />
      </div>
      <p class="app-mark-kind">{selected.kind}</p>
      <p class="ui-reading">{selected.reading}</p>
      <p class="app-mark-source ui-mono">{selected.source}</p>
      <div class="app-mark-actions">
        <Button size="sm" icon="plus" disabled>Add to trip</Button>
        <Button size="sm" icon="download" disabled>GPX</Button>
        <Button size="sm" icon="shield" disabled>Regulations</Button>
      </div>
      <Popover>{selected.basis}</Popover>
    </section>
  );
}
