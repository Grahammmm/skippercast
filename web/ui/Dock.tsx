// Time dock (FE-03, design § 6): day chips, play or pause, the hour slider
// and a mono readout, in one bar over the map (desktop) or at the sheet's
// top edge (mobile, FE-06). Range is the labelled <input type="range"> it
// uses; the hour's text is exposed as aria-valuetext so a screen reader
// hears "2 pm", not "14". FE-05 binds the dock to the day and hour signals.
import {IconButton} from './Button.tsx';
import {Segmented, type SegmentedOption} from './Chip.tsx';
import {t} from '../i18n.ts';

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

/** The dock's accessible names and button labels; the English default is the catalogue's. */
export interface DockLabels {time: string; day: string; hour: string; play: string; pause: string; nextHour: string}
const ENGLISH: DockLabels = {time: t('shell.time'), day: t('shell.day'), hour: t('shell.hour'), play: t('dock.play'), pause: t('dock.pause'), nextHour: t('dock.nextHour')};

export type DockProps<D extends string> = {
  labels?: DockLabels;
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
  /** No hours to step through (observations only): slider and play disabled. A day with one hour left still plays on into the next (FE-12). */
  disabled?: boolean;
  /** prefers-reduced-motion: the button steps one hour per press ("Next hour") instead of playing. */
  stepOnly?: boolean;
  /** No later hour in the whole forecast horizon; keep the slider and an active Pause usable. */
  advanceDisabled?: boolean;
  class?: string;
};

export function Dock<D extends string>({days, day, onDay, playing, onPlay, hour, hours, onHour, hourText, labels = ENGLISH, disabled = false, stepOnly = false, advanceDisabled = false, class: cls}: DockProps<D>) {
  return (
    <div class={['ui-dock', cls].filter(Boolean).join(' ')} role="group" aria-label={labels.time}>
      <Segmented label={labels.day} options={days} value={day} onChange={onDay} />
      {stepOnly
        ? <IconButton icon="chevron" label={labels.nextHour} disabled={disabled || advanceDisabled} onClick={() => onPlay(true)} />
        : <IconButton icon={playing ? 'pause' : 'play'} label={playing ? labels.pause : labels.play} pressed={playing} disabled={disabled || (advanceDisabled && !playing)} onClick={() => onPlay(!playing)} />}
      <Range label={labels.hour} value={hour} max={Math.max(0, hours - 1)} onChange={onHour} valueText={hourText} disabled={disabled} class="ui-dock-range" />
      <output class="ui-dock-readout ui-mono" aria-live="off">{hourText(hour)}</output>
    </div>
  );
}
