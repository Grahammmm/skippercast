// Bottom sheet (FE-03, design § 6 mobile): three detents, peek, half and
// full, set by the parent and moved by the handle, a real button: click or
// Enter steps up (full steps back to peek), ArrowUp and ArrowDown step,
// Home is peek, End is full, Escape is peek. ui.css positions the sheet by
// data-detent with the --motion-sheet transition. FE-06 adds drag and the
// hour slider at the top edge (the `edge` slot).
import type {ComponentChildren} from 'preact';

export const DETENTS = ['peek', 'half', 'full'] as const;
export type Detent = (typeof DETENTS)[number];

/** The detent a key moves to, or null when the key is not the sheet's. */
export function nextDetent(current: Detent, key: string): Detent | null {
  const at = DETENTS.indexOf(current);
  switch (key) {
    case 'ArrowUp': return DETENTS[Math.min(at + 1, DETENTS.length - 1)] ?? current;
    case 'ArrowDown': return DETENTS[Math.max(at - 1, 0)] ?? current;
    case 'Home': case 'Escape': return 'peek';
    case 'End': return 'full';
    default: return null;
  }
}

/** The detent a click on the handle moves to: up, then back to peek. */
export const stepDetent = (current: Detent): Detent => (current === 'full' ? 'peek' : nextDetent(current, 'ArrowUp') ?? 'peek');

export type SheetProps = {
  /** The sheet's accessible name ("Brief"). */
  label: string;
  detent: Detent;
  onDetent: (detent: Detent) => void;
  /** Content pinned at the top edge beside the handle (the hour slider). */
  edge?: ComponentChildren;
  children: ComponentChildren;
  class?: string;
};

export function Sheet({label, detent, onDetent, edge, children, class: cls}: SheetProps) {
  const onKeyDown = (event: KeyboardEvent) => {
    const next = nextDetent(detent, event.key);
    if (next === null) return;
    event.preventDefault();
    if (next !== detent) onDetent(next);
  };
  return (
    <section class={['ui-sheet', cls].filter(Boolean).join(' ')} data-detent={detent} aria-label={label}>
      <div class="ui-sheet-edge">
        <button type="button" class="ui-sheet-handle" aria-label={`${detent === 'full' ? 'Collapse' : 'Expand'} ${label}`}
          aria-expanded={detent !== 'peek'} data-detent={detent} onClick={() => onDetent(stepDetent(detent))} onKeyDown={onKeyDown}>
          <span class="ui-sheet-grip" aria-hidden="true"></span>
        </button>
        {edge}
      </div>
      <div class="ui-sheet-body">{children}</div>
    </section>
  );
}
