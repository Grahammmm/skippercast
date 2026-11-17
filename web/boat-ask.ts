// Reader-free first-use navigation shared by the landing and app.
// The landing navigates as soon as a profile is chosen, so a Boat choice there
// asks for the boat on the map it opens, by the map's FirstRun: the landing
// marks it in session storage, or — when storage is refused — as
// ?boat-entry=ask, which the map reads once and drops from the address. The
// save's notices are then said on the map, where the boat is saved.
export const ASK_KEY = 'skippercast-first-use-boat';
export const ASK_PARAM = 'boat-entry';
export type AskStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function browserSession(): AskStorage | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; }
}

/** `url` asking the page it opens for the boat. Never throws. */
export function carryAsk(url: string, session: AskStorage | null = browserSession()): string {
  try {
    if (!session) throw new Error('no session storage');
    session.setItem(ASK_KEY, 'ask');
    return url;
  } catch {
    const next = new URL(url);
    next.searchParams.set(ASK_PARAM, 'ask');
    return next.href;
  }
}

/** Whether `href` was opened asking for the boat, read once (the stored mark is removed). Never throws. */
export function takeAsk(href: string, session: AskStorage | null = browserSession()): boolean {
  let ask = false;
  try {
    // Admit the carried ask before the best-effort cleanup, so a failed removal cannot revoke it.
    if (session?.getItem(ASK_KEY)) { ask = true; session.removeItem(ASK_KEY); }
  } catch { /* nothing carried, or the mark could not be removed */ }
  try {
    if (new URL(href).searchParams.get(ASK_PARAM) === 'ask') ask = true;
  } catch { /* not a URL */ }
  return ask;
}

/** `href` without the carried ask, so a reload or a shared link does not repeat it. */
export function withoutAsk(href: string): string {
  const url = new URL(href);
  url.searchParams.delete(ASK_PARAM);
  return url.href;
}
