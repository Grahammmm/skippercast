// Selected-mark card (FE-05, design § 9): one card for whatever the link
// selects (?spot= or ?focus=), with name, kind, reading, source and age, the
// action row and a basis link. The engine (FE-11) fills the reading and the
// source; until then the card names the selection and shows "—".
import {Button, IconButton} from '../ui/Button.tsx';
import {Popover} from '../ui/Popover.tsx';
import {navigate, selection} from '../state.ts';

export interface Mark {readonly id: string; readonly name: string; readonly kind: string; readonly reading: string; readonly source: string; readonly basis: string}

/** The card's placeholder for a selection the engine has not resolved. */
export const placeholderMark = (id: string): Mark => ({id, name: id, kind: 'Mark', reading: '—', source: 'Source —', basis: 'The mark loads with the map engine; its source and age show here.'});

/** Drop the selection from the address (?spot= and ?focus= are read, never written, by the store). */
export function clearSelection(href: string): string {
  const url = new URL(href);
  url.searchParams.delete('spot'); url.searchParams.delete('focus');
  return url.href;
}

export function MarkCard({mark}: {mark?: Mark} = {}) {
  const selected = mark ?? (selection.value ? placeholderMark(selection.value) : null);
  if (!selected) return null;
  return (
    <section class="app-mark" aria-label="Selected mark">
      <div class="app-mark-head">
        <h2>{selected.name}</h2>
        <IconButton icon="close" label="Clear selection" size="sm" onClick={() => navigate(clearSelection(location.href), {replace: true})} />
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
