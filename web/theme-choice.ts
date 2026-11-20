// Device-local display choice, independent of account and map data.
import {signal} from '@preact/signals';
import {applyTheme, lightScheme, readThemeChoice, THEME_KEY, type ThemeChoice} from './theme-boot.ts';

export type {ThemeChoice};
const scheme = lightScheme();
export const themeChoice = signal<ThemeChoice>(readThemeChoice());
applyTheme(themeChoice.peek(), scheme?.matches ?? false);
scheme?.addEventListener('change', event => {
  if (themeChoice.peek() === 'auto') applyTheme('auto', event.matches);
});

export function setThemeChoice(next: ThemeChoice): void {
  if (next !== 'auto' && next !== 'light' && next !== 'dark') return;
  applyTheme(next, scheme?.matches ?? false);
  themeChoice.value = next;
  try { localStorage.setItem(THEME_KEY, next); } catch { /* This page still uses the choice. */ }
}
