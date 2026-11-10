// Deterministic stand-ins for the hooks and the one check dependency, used to mount the real PositionCheck component. Test-only.
export const rt = {slots: [], cursor: 0, effects: [], calls: [], lists: 0, region: {value: 'morro-bay'}, open: {value: true}};
export function reset() { Object.assign(rt, {slots: [], cursor: 0, effects: [], calls: [], lists: 0}); rt.region.value = 'morro-bay'; rt.open.value = true; }
export function unmount() { for (const s of rt.slots) s?.cleanup?.(); }
export function useState(initial) { const i = rt.cursor++; if (!(i in rt.slots)) rt.slots[i] = initial; return [rt.slots[i], v => { rt.slots[i] = v; }]; }
export function useRef(initial) { const i = rt.cursor++; return rt.slots[i] ??= {current: initial}; }
export function useEffect(fn, deps) {
  const i = rt.cursor++, old = rt.slots[i];
  if (!old || deps.some((v, j) => v !== old.deps[j])) rt.effects.push(() => { old?.cleanup?.(); rt.slots[i] = {deps, cleanup: fn()}; });
}
export const region = rt.region, tripOpen = rt.open, language = {value: 'en'};
export function listPacks() { rt.lists++; return Promise.resolve([]); }
export function loadProtectedScreen() { return Promise.resolve({state: 'none'}); }
export function checkPosition() { return new Promise(resolve => rt.calls.push(resolve)); }
export function packState(_packs, id) { return 'none:' + id; }
export function PositionView() { return null; }
