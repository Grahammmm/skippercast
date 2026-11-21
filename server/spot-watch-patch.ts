import {validateWatchInput, type WatchInput} from './spot-watch-rules.ts';

type Watch = Extract<WatchInput, {ok: true}>['watch'] & {enabled: boolean};
type WatchPatchResult =
  | {ok: true; watch: Watch; resetState: boolean}
  | Extract<WatchInput, {ok: false}>
  | {ok: false; field: 'enabled'; error: string};

export function mergeWatchPatch(current: Watch, patch: unknown): WatchPatchResult {
  try {
    if (patch === null || typeof patch !== 'object' || Array.isArray(patch)) {
      return {ok: false, field: 'body', error: 'Expected a plain watch patch object.'};
    }
    const prototype = Object.getPrototypeOf(patch);
    if (prototype !== Object.prototype && prototype !== null) {
      return {ok: false, field: 'body', error: 'Expected a plain watch patch object.'};
    }
    const keys = Reflect.ownKeys(patch);
    if (keys.length === 0) return {ok: false, field: 'body', error: 'Expected at least one watch patch key.'};

    const values = new Map<keyof Watch, unknown>();
    for (const key of keys) {
      if (key !== 'layer' && key !== 'op' && key !== 'a' && key !== 'b' && key !== 'enabled') {
        return {ok: false, field: 'body', error: 'Unexpected watch patch key.'};
      }
      const descriptor = Object.getOwnPropertyDescriptor(patch, key);
      if (!descriptor || !Object.hasOwn(descriptor, 'value')) {
        return {ok: false, field: 'body', error: 'Expected own data properties in the watch patch.'};
      }
      values.set(key, descriptor.value);
    }

    const {layer, op, a, b, enabled} = current;
    const mergedOp = values.has('op') ? values.get('op') : op;
    const result = validateWatchInput({
      layer: values.has('layer') ? values.get('layer') : layer,
      op: mergedOp,
      a: values.has('a') ? values.get('a') : a,
      b: values.has('b') ? values.get('b') : mergedOp === 'between' ? b : null,
    });
    if (!result.ok) return result;

    const mergedEnabled = values.has('enabled') ? values.get('enabled') : enabled;
    if (typeof mergedEnabled !== 'boolean') {
      return {ok: false, field: 'enabled', error: 'Expected a boolean.'};
    }
    const watch = result.watch;
    return {
      ok: true,
      watch: {...watch, enabled: mergedEnabled},
      resetState: watch.layer !== layer || watch.op !== op || watch.a !== a || watch.b !== b,
    };
  } catch {
    // Reflecting on a revoked or throwing proxy can fail even without invoking a getter.
    return {ok: false, field: 'body', error: 'Could not inspect watch patch.'};
  }
}
