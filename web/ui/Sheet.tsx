// Bottom sheet (FE-03, design § 6 mobile): three detents, peek, half and
// full, set by the parent and moved by the handle, a real button: click or
// Enter steps up (full steps back to peek), ArrowUp and ArrowDown step,
// Home is peek, End is full, Escape is peek. ui.css positions the sheet by
// data-detent with the --motion-sheet transition. FE-06 added drag: the
// handle follows the pointer, and on release the sheet snaps one detent in
// the drag's direction (past DRAG_FAR of its height, to the end), or back;
// a move under TAP_MAX is a tap and clicks.
// The `edge` slot pins content beside the handle (the hour slider).
import type {ComponentChildren} from 'preact';
import {useRef} from 'preact/hooks';

export const DETENTS = ['peek', 'half', 'full'] as const;
export type Detent = (typeof DETENTS)[number];
/** A drag shorter than this snaps back. */
export const DRAG_MIN = 48;
/** A pointer that moves less than this is a tap and clicks the handle; further and the click is swallowed. */
export const TAP_MAX = 12;
/** A drag past this share of the sheet's height goes to the end detent. */
export const DRAG_FAR = 0.45;

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

/** The detent a drag of `dy` px (negative is up) over a sheet `height` px tall releases to. */
export function dragDetent(current: Detent, dy: number, height: number): Detent {
  if (Math.abs(dy) < DRAG_MIN) return current;
  const up = dy < 0;
  if (Math.abs(dy) > height * DRAG_FAR) return up ? 'full' : 'peek';
  return nextDetent(current, up ? 'ArrowUp' : 'ArrowDown') ?? current;
}

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

type Drag = {y: number; base: number; sheet: HTMLElement; moved: boolean};

export function Sheet({label, detent, onDetent, edge, children, class: cls}: SheetProps) {
  const drag = useRef<Drag | null>(null);
  const onKeyDown = (event: KeyboardEvent) => {
    const next = nextDetent(detent, event.key);
    if (next === null) return;
    event.preventDefault();
    if (next !== detent) onDetent(next);
  };
  const onPointerDown = (event: PointerEvent) => {
    const handle = event.currentTarget as HTMLElement, sheet = handle.closest<HTMLElement>('.ui-sheet');
    if (!sheet || event.button !== 0) return;
    const base = new DOMMatrixReadOnly(getComputedStyle(sheet).transform).m42;
    // A cancelled drag (pointercancel fires no click) would otherwise leave the flag to swallow the next tap.
    delete handle.dataset.dragged;
    drag.current = {y: event.clientY, base, sheet, moved: false};
    handle.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dy = event.clientY - d.y;
    if (Math.abs(dy) >= TAP_MAX) d.moved = true;
    d.sheet.style.transition = 'none';
    d.sheet.style.transform = `translateY(${Math.max(0, d.base + dy)}px)`;
  };
  const onPointerUp = (event: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    d.sheet.style.transition = '';
    d.sheet.style.transform = '';
    const next = dragDetent(detent, event.clientY - d.y, d.sheet.offsetHeight);
    if (next !== detent) onDetent(next);
    if (d.moved) (event.currentTarget as HTMLElement).dataset.dragged = 'true';
  };
  const onClick = (event: MouseEvent) => {
    const handle = event.currentTarget as HTMLElement;
    if (handle.dataset.dragged) { delete handle.dataset.dragged; return; }
    onDetent(stepDetent(detent));
  };
  return (
    <section class={['ui-sheet', cls].filter(Boolean).join(' ')} data-detent={detent} aria-label={label}>
      <div class="ui-sheet-edge">
        <button type="button" class="ui-sheet-handle" aria-label={`${detent === 'full' ? 'Collapse' : 'Expand'} ${label}`}
          aria-expanded={detent !== 'peek'} data-detent={detent} onClick={onClick} onKeyDown={onKeyDown}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
          <span class="ui-sheet-grip" aria-hidden="true"></span>
        </button>
        {edge}
      </div>
      <div class="ui-sheet-body">{children}</div>
    </section>
  );
}
