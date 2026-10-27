// Deterministic hook scheduler: complete Trip module + installed Preact SSR.
// This is not a DOM, browser storage, or browser lifecycle qualification.
export const runtime = {slots: [], cursor: 0, effects: [], actions: new Map(), responses: [], calls: 0, deletes: [], saves: 0};
export function reset(responses) {
  Object.assign(runtime, {slots: [], cursor: 0, effects: [], actions: new Map(), responses: [...responses], calls: 0, deletes: [], saves: 0});
}
export function useState(initial) {
  const at = runtime.cursor++;
  if (!(at in runtime.slots)) runtime.slots[at] = typeof initial === 'function' ? initial() : initial;
  return [runtime.slots[at], next => { runtime.slots[at] = typeof next === 'function' ? next(runtime.slots[at]) : next; }];
}
export function useRef(initial) {
  const [ref] = useState(() => ({current: initial}));
  return ref;
}
export function useEffect(callback, dependencies) {
  const at = runtime.cursor++, previous = runtime.slots[at];
  if (!previous || dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))) {
    runtime.effects.push(() => {
      previous?.cleanup?.();
      runtime.slots[at] = {dependencies, cleanup: callback()};
    });
  }
}
export function cleanup() {
  for (const slot of runtime.slots) slot?.cleanup?.();
}
export function listPacks() {
  runtime.calls++;
  if (!runtime.responses.length) throw new Error('unexpected synthetic listPacks call');
  return runtime.responses.shift()();
}
