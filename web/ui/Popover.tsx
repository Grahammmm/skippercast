// Basis popover (FE-03, design § 12, D13): one sentence naming the product,
// its resolution and its age rule, inside a <details> so the copy lint reads
// it as a disclosure and keyboards open it natively (Enter or Space on the
// summary, Escape is the browser's). The summary is the trigger: "basis" by
// default, or an info icon with that label.
import type {ComponentChildren} from 'preact';
import {Icon} from './icons.tsx';

export type PopoverProps = {
  /** The summary text; the default reads "basis". */
  summary?: string;
  /** Show the info icon instead of the summary text (the text stays as the accessible name). */
  iconOnly?: boolean;
  /** Opens to the left of its trigger (for the map's right-hand rail). */
  align?: 'start' | 'end';
  children: ComponentChildren;
  class?: string;
};

export function Popover({summary = 'basis', iconOnly = false, align = 'start', children, class: cls}: PopoverProps) {
  return (
    <details class={['ui-popover', iconOnly ? 'ui-popover--icon' : '', cls].filter(Boolean).join(' ')} data-align={align}>
      <summary class="ui-popover-summary ui-eyebrow" aria-label={iconOnly ? summary : undefined}>
        {iconOnly ? <Icon name="info" size={16} /> : summary}
      </summary>
      <div class="ui-popover-body">{children}</div>
    </details>
  );
}
