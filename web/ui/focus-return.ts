// One focus-return rule for the app's blocking overlays (R-P1, e2e/overlay-keyboard.spec.ts): an overlay remembers what had
// focus when it opened and gives focus back on close, falling back to the masthead account trigger when that element is gone
// or hidden (a dialog opened from another dialog); with no opener it does nothing. A click on the scrim of a native modal dialog closes it.

/** The element that has focus now, or null when focus is on the page itself. */
export function rememberOpener(): HTMLElement | null {
  const active = document.activeElement;
  return active instanceof HTMLElement && active !== document.body ? active : null;
}

/** Give focus back to `opener`; when it cannot take it, to the masthead account trigger. No opener (opened by a link or a reload): focus stays where it is. */
export function restoreFocus(opener: HTMLElement | null): void {
  if (!opener) return;
  for (const target of [opener, document.querySelector<HTMLElement>('.app-account-trigger')]) {
    if (!target?.isConnected) continue;
    target.focus();
    if (document.activeElement === target) return;
  }
}

/** `onClick` for a native `<dialog>`: a click on its backdrop (the event lands on the dialog, outside its box) closes it. */
export function closeOnScrim(event: MouseEvent): void {
  const dialog = event.currentTarget as HTMLDialogElement, box = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
}
