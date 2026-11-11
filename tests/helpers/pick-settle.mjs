// RF2205-5: the engine settles a click for 550 ms before it picks. Importing this file captures those
// timers (nothing else is touched) so a test can fire a click and call settlePicks() to run what is pending, synchronously.
const real = {setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout};
const pending = new Map();
export const PICK_SETTLE_MS = 550;
globalThis.setTimeout = (fn, ms, ...args) => {
  if (ms !== PICK_SETTLE_MS) return real.setTimeout(fn, ms, ...args);
  const id = {pick: true}; pending.set(id, fn); return id;
};
globalThis.clearTimeout = id => { if (id && pending.has(id)) pending.delete(id); else real.clearTimeout(id); };
/** Run every pending settled click now; returns how many ran. */
export function settlePicks() { const run = [...pending.values()]; pending.clear(); for (const fn of run) fn(); return run.length; }
/** How many clicks are still settling. */
export const settling = () => pending.size;
