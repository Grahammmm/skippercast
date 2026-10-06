// Chips (FE-03, design § 6 and § 7): a pill toggle (aria-pressed) and a
// Segmented group of them with exactly one on, for the Boat / Shore / Spear
// profile switch, the landing's profile pills and the time dock's day chips.
import {Button, type ButtonProps} from './Button.tsx';
import type {IconName} from './icons.tsx';

export type ChipProps = Omit<ButtonProps, 'variant' | 'size'> & {on?: boolean};

export function Chip({on = false, class: cls, ...rest}: ChipProps) {
  return <Button {...rest} variant="ghost" size="sm" pressed={on} class={['ui-chip', cls].filter(Boolean).join(' ')} />;
}

export type SegmentedOption<T extends string> = {value: T; label: string; icon?: IconName};

export type SegmentedProps<T extends string> = {
  /** The group's accessible name ("Profile", "Day"). */
  label: string;
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  class?: string;
};

export function Segmented<T extends string>({label, options, value, onChange, class: cls}: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} class={['ui-segmented', cls].filter(Boolean).join(' ')}>
      {options.map(option => (
        <Chip key={option.value} on={option.value === value} icon={option.icon} onClick={() => onChange(option.value)}>
          {option.label}
        </Chip>
      ))}
    </div>
  );
}
