// Confidence badge (guide §5.5): Qualified ✓ / Estimated ~ / Unknown ? with a
// one-line "why". The badge is a disclosure button, so the why opens by tap,
// click, Enter or Space; Escape or a tap elsewhere closes it and Escape
// returns focus to the badge (without closing the sheet around it). The why
// is always in the DOM (hidden when closed), never a `title` tooltip.
import {useEffect, useRef, useState} from 'preact/hooks';
import {BADGE_MARK, BADGE_WORD, type Badge} from '../confidence.ts';

let sequence = 0;

export function ConfidenceBadge({label, state, why, defaultOpen = false}: Omit<Badge, 'id' | 'open'> & {defaultOpen?: boolean}) {
  const [open, setOpen] = useState(defaultOpen);
  const [whyId] = useState(() => `confidence-why-${++sequence}`);
  const wrap = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [open]);
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== 'Escape' || !open) return;
    // Handled here: a modal <dialog> would otherwise close on this Escape.
    event.preventDefault();
    event.stopPropagation();
    setOpen(false);
    button.current?.focus();
  };
  return (
    <span ref={wrap} class="confidence-badge" data-state={state} onKeyDown={onKeyDown}>
      <button ref={button} type="button" class="confidence-badge-button" aria-expanded={open} aria-controls={whyId}
        onClick={() => setOpen(!open)}>
        <span class="confidence-mark" aria-hidden="true">{BADGE_MARK[state]}</span>
        {label} <span class="confidence-state">{BADGE_WORD[state]}</span>
      </button>
      <span id={whyId} class="confidence-why" hidden={!open}>
        {why.lead ? <><strong>{why.lead}</strong> </> : null}
        {why.text}
        {why.link ? <> <a href={why.link.href}>{why.link.text}</a></> : null}
      </span>
    </span>
  );
}
