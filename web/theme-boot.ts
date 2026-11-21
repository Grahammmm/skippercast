// Shared by the blocking head script and the live app. Keep this module free
// of UI dependencies so the head script can run before any app code arrives.
export type ThemeChoice = 'auto' | 'light' | 'dark';
export const THEME_KEY = 'skippercast-theme-v1';
const LIGHT_SCHEME = '(prefers-color-scheme: light)';

export function lightScheme(): MediaQueryList | undefined {
  return globalThis.matchMedia?.(LIGHT_SCHEME);
}

export function readThemeChoice(): ThemeChoice {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch { /* Missing or blocked storage uses Auto. */ }
  return 'auto';
}

export function applyTheme(choice: ThemeChoice, prefersLight: boolean): void {
  const root = globalThis.document?.documentElement;
  if (!root) return;
  if (choice === 'light' || (choice === 'auto' && prefersLight)) {
    if (root.dataset.theme !== 'light') root.dataset.theme = 'light';
  } else {
    delete root.dataset.theme;
  }
}

export function bootTheme(): void {
  applyTheme(readThemeChoice(), lightScheme()?.matches ?? false);
}
