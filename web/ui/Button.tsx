// Buttons (FE-03, design § 5 and § 6): real <button>s styled by web/ui/ui.css
// from tokens only, with a focus ring and a 44 px target. A toggle carries
// aria-pressed; an icon-only button always has a visible-to-AT label.
import type {ComponentChildren, JSX} from 'preact';
import {Icon, type IconName} from './icons.tsx';

type Native = Omit<JSX.ButtonHTMLAttributes<HTMLButtonElement>, 'icon' | 'size' | 'label'>;

export type ButtonProps = Native & {
  /** primary: the one mint action; ghost: outlined; quiet: text only. */
  variant?: 'primary' | 'ghost' | 'quiet';
  size?: 'md' | 'sm';
  icon?: IconName;
  /** For a toggle: renders aria-pressed and data-on. */
  pressed?: boolean;
  children?: ComponentChildren;
};

export function Button({variant = 'ghost', size = 'md', icon, pressed, class: cls, children, type = 'button', ...rest}: ButtonProps) {
  return (
    <button {...rest} type={type} class={['ui-button', `ui-button--${variant}`, size === 'sm' ? 'ui-button--sm' : '', cls].filter(Boolean).join(' ')}
      aria-pressed={pressed === undefined ? undefined : pressed} data-on={pressed ? 'true' : undefined}>
      {icon ? <Icon name={icon} size={size === 'sm' ? 16 : 18} /> : null}
      {children}
    </button>
  );
}

export type IconButtonProps = Omit<ButtonProps, 'icon' | 'children'> & {
  icon: IconName;
  /** The accessible name (there is no visible text). */
  label: string;
};

export function IconButton({icon, label, variant = 'quiet', size = 'md', class: cls, ...rest}: IconButtonProps) {
  return (
    <Button {...rest} variant={variant} size={size} class={['ui-icon-button', cls].filter(Boolean).join(' ')} aria-label={label} title={label}>
      <Icon name={icon} size={size === 'sm' ? 16 : 20} />
    </Button>
  );
}
