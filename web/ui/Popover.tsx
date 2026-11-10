// Basis popover (FE-03, design § 12, D13): one sentence naming the product,
// its resolution and its age rule, inside a <details> so the copy lint reads
// it as a disclosure and keyboards open it natively (Enter or Space on the
// summary). A <details> does not close on Escape by itself, so the one local
// key handler below does: Escape closes the open disclosure that owns the key
// event and puts focus back on its own summary. The summary is the trigger:
// "basis" by default, or an info icon with that label.
import type {ComponentChildren} from 'preact';
import {Icon} from './icons.tsx';
import {language, t} from '../i18n.ts';

export type PopoverProps = {
  /** The summary text; the default reads "basis". */
  summary?: string;
  /** Show the info icon instead of the summary text (the text stays as the accessible name). */
  iconOnly?: boolean;
  /** Opens to the left of its trigger (for the map's right-hand rail). */
  align?: 'start' | 'end';
  children: ComponentChildren;
  class?: string;
  /** The sources page the basis links into; false for a popover that is not a basis. */
  sources?: string | false;
};

/** The canonical sources page (open-questions Q16; the Worker serves dist/sources.html there). */
export const SOURCES_PAGE = '/sources';

/** Escape on an open disclosure closes it, focuses its own summary and stops there, so an enclosing dialog or outer disclosure stays put. */
function closeOnEscape(event: KeyboardEvent) {
  const details = event.currentTarget as HTMLDetailsElement;
  if (event.key !== 'Escape' || event.defaultPrevented || !details.open) return;
  const summary = Array.from(details.children as ArrayLike<Element>).find(child => child.tagName === 'SUMMARY') as HTMLElement | undefined;
  // A handler inside the disclosure that already moved focus out of it (the share link field returns to its Share button) keeps that focus.
  const active = details.ownerDocument?.activeElement;
  const movedOut = !!active && active !== details.ownerDocument.body && !details.contains(active);
  details.open = false;
  if (!movedOut) summary?.focus();
  event.preventDefault();
  event.stopPropagation();
}

export function Popover({summary: given, iconOnly = false, align = 'start', children, class: cls, sources = SOURCES_PAGE}: PopoverProps) {
  const lang = language.value, summary = given ?? t('shared.popover.basis', lang);
  return (
    <details class={['ui-popover', iconOnly ? 'ui-popover--icon' : '', cls].filter(Boolean).join(' ')} data-align={align} onKeyDown={closeOnEscape}>
      <summary class="ui-popover-summary ui-eyebrow" aria-label={iconOnly ? summary : undefined}>
        {iconOnly ? <Icon name="info" size={16} /> : summary}
      </summary>
      <div class="ui-popover-body">{children}{sources ? <p class="ui-popover-sources"><a href={sources}>{t('shared.popover.sources', lang)}</a></p> : null}</div>
    </details>
  );
}
