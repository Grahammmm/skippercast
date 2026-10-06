// Time dock (FE-03, design § 6): day chips, play or pause, the hour slider
// and a mono readout, in one bar over the map (desktop) or at the sheet's
// top edge (mobile, FE-06). Range is the labelled <input type="range"> it
// uses; the hour's text is exposed as aria-valuetext so a screen reader
// hears "2 pm", not "14". FE-05 binds the dock to the day and hour signals.
import {IconButton} from './Button.tsx';
import {Segmented, type SegmentedOption} from './Chip.tsx';

export type RangeProps = {
  /** The accessible name ("Hour"). */
  label: string;
  value: number;
  min?: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  /** Text for the current value ("2 pm"), read by assistive technology. */
  valueText?: (value: number) => string;
  disabled?: boolean;
  class?: string;
};

export function Range({label, value, min = 0, max, step = 1, onChange, valueText, disabled, class: cls}: RangeProps) {
  return (
    <input type="range" class={['ui-range', cls].filter(Boolean).join(' ')} aria-label={label} aria-valuetext={valueText ? valueText(value) : undefined}
      min={min} max={max} step={step} value={value} disabled={disabled}
      onInput={event => onChange(Number((event.currentTarget as HTMLInputElement).value))} />
  );
}

export type DockProps<D extends string> = {
  days: ReadonlyArray<SegmentedOption<D>>;
  day: D;
  onDay: (day: D) => void;
  playing: boolean;
  onPlay: (playing: boolean) => void;
  /** Index of the shown hour and the count of hours for the day. */
  hour: number;
  hours: number;
  onHour: (hour: number) => void;
  /** The hour as text ("2 pm"); shown in mono and read with the slider. */
  hourText: (hour: number) => string;
  /** No hours to step through (observations only): slider and play disabled. */
  disabled?: boolean;
  class?: string;
};

export function Dock<D extends string>({days, day, onDay, playing, onPlay, hour, hours, onHour, hourText, disabled = false, class: cls}: DockProps<D>) {
  const still = disabled || hours < 2;
  return (
    <div class={['ui-dock', cls].filter(Boolean).join(' ')} role="group" aria-label="Time">
      <Segmented label="Day" options={days} value={day} onChange={onDay} />
      <IconButton icon={playing ? 'pause' : 'play'} label={playing ? 'Pause' : 'Play'} pressed={playing} disabled={still} onClick={() => onPlay(!playing)} />
      <Range label="Hour" value={hour} max={Math.max(0, hours - 1)} onChange={onHour} valueText={hourText} disabled={still} class="ui-dock-range" />
      <output class="ui-dock-readout ui-mono" aria-live="off">{hourText(hour)}</output>
    </div>
  );
}
