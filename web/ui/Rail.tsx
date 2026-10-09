// Layer rail (FE-03, design § 6 and § 9): the map's one list of layer
// toggles. Each entry is a real toggle button (aria-pressed) with its icon
// and name, an optional note ("no fresh frame 14:00") and its basis sentence
// in an info Popover opening away from the map edge. FE-05 binds it to the
// layer registry; on mobile FE-06 shows it inside a Sheet.
import type {ComponentChildren} from 'preact';
import {Button} from './Button.tsx';
import type {IconName} from './icons.tsx';
import {Popover} from './Popover.tsx';

export type RailItemProps = {
  id: string;
  label: string;
  icon: IconName;
  on: boolean;
  onToggle: (id: string, on: boolean) => void;
  /** Shown under the name in mono ("no fresh frame 14:00", "admin"). */
  note?: string;
  /** The basis sentence, rendered in a Popover. */
  basis?: ComponentChildren;
  disabled?: boolean;
  /** Controls of the entry itself (the Currents source), shown under it. */
  children?: ComponentChildren;
};

export function RailItem({id, label, icon, on, onToggle, note, basis, disabled, children}: RailItemProps) {
  return (
    <li class="ui-rail-item" data-on={on ? 'true' : 'false'}>
      <Button icon={icon} pressed={on} disabled={disabled} class="ui-rail-toggle" onClick={() => onToggle(id, !on)}>
        <span class="ui-rail-text">
          <span class="ui-rail-label">{label}</span>
          {note ? <span class="ui-rail-note ui-mono">{note}</span> : null}
        </span>
      </Button>
      {basis ? <Popover iconOnly align="end" summary={`${label} basis`}>{basis}</Popover> : null}
      {children}
    </li>
  );
}

export function Rail({label = 'Layers', children, class: cls}: {label?: string; children: ComponentChildren; class?: string}) {
  return (
    <div class={['ui-rail', cls].filter(Boolean).join(' ')} role="group" aria-label={label}>
      <ul class="ui-rail-list">{children}</ul>
    </div>
  );
}
