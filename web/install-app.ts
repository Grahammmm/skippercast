import {signal} from '@preact/signals';

type InstallEvent = Event & {prompt(): Promise<unknown>};
export const installable = signal<InstallEvent | null>(null);
const watched = new WeakSet<Window>();

export function isStandalone(win: Window): boolean {
  return win.matchMedia('(display-mode: standalone)').matches ||
    (win.navigator as Navigator & {standalone?: boolean}).standalone === true;
}
export function isIosSafari(ua: string): boolean {
  return /iPhone|iPad|iPod/.test(ua) && /Safari\//.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(ua);
}
export function watchInstall(win: Window): void {
  if (watched.has(win)) return;
  watched.add(win);
  win.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installable.value = event as InstallEvent;
  });
  win.addEventListener('appinstalled', () => { installable.value = null; });
}
export async function requestInstall(): Promise<void> {
  const event = installable.peek();
  installable.value = null; // Consume before prompting: double clicks cannot reuse the event.
  if (!event) return;
  try { await event.prompt(); } catch { /* Dismissed or expired: wait for a new browser offer. */ }
}
