// Stat tile (FE-03, design § 10): one reading with its label, unit, source
// and age in mono, a stale state past the source's limit, and its basis in a
// Popover. The tile shows what it has; a missing reading renders the given
// placeholder ("no fresh buoy") rather than a guess.
import type {ComponentChildren} from 'preact';
import {Icon, type IconName} from './icons.tsx';
import {Popover} from './Popover.tsx';

export type TileHue = 'mint' | 'blue' | 'coral' | 'amber';

export type TileProps = {
  label: string;
  icon?: IconName;
  /** Reading colour: wind mint, swell blue, water coral, tide amber (§ 5). */
  hue?: TileHue;
  /** The reading as already formatted text ("12", "4.1", "no fresh buoy"). */
  reading: string;
  unit?: string;
  /** A second line under the reading (direction, period, trend). */
  detail?: string;
  /** Source and age, in mono ("NWS 2 h", "Buoy 46011 14 min"). */
  source?: string;
  /** Past the source's limit: the tile is marked stale and says so. */
  stale?: boolean;
  /** The basis sentence (goes inside a <details>). */
  basis?: ComponentChildren;
  class?: string;
};

export function Tile({label, icon, hue, reading, unit, detail, source, stale = false, basis, class: cls}: TileProps) {
  return (
    <div class={['ui-tile', cls].filter(Boolean).join(' ')} data-hue={hue} data-state={stale ? 'stale' : 'ok'}>
      <div class="ui-tile-label ui-eyebrow">
        {icon ? <Icon name={icon} size={14} /> : null}
        <span>{label}</span>
      </div>
      <div class="ui-tile-reading">
        <span class="ui-reading">{reading}</span>
        {unit ? <span class="ui-tile-unit">{unit}</span> : null}
      </div>
      {detail ? <div class="ui-tile-detail">{detail}</div> : null}
      {source || stale ? (
        <div class="ui-tile-source">
          {source ? <span class="ui-mono">{source}</span> : null}
          {stale ? <span class="ui-tile-stale ui-eyebrow">stale</span> : null}
        </div>
      ) : null}
      {basis ? <Popover>{basis}</Popover> : null}
    </div>
  );
}
