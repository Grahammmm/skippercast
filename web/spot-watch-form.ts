import {WATCH_OPS, type WatchOp} from '../server/spot-watch-rules.ts';
import {WATCH_RANGES, fromStored, toStored, type WatchLayer} from './spot-watch-units.ts';
import type {Units} from './unit-choice.ts';

type WatchForm = {layer: string; op: string; a: string; b: string};
type WatchBody = {layer: WatchLayer; op: WatchOp; a: number; b: number | null};
type Temp = Units['temp'];
type ValueError = 'required' | 'not-a-number' | 'out-of-range';
type FormResult =
  | {ok: true; body: WatchBody}
  | {ok: false; field: keyof WatchForm; error: ValueError | 'order'};

function isWatchLayer(layer: string): layer is WatchLayer {
  return Object.hasOwn(WATCH_RANGES, layer);
}

function parseValue(text: string, layer: WatchLayer, temp: Temp): number | ValueError {
  const value = text.trim();
  if (value === '') return 'required';
  if (!/^-?\d+(?:[.,]\d+)?$/.test(value)) return 'not-a-number';
  return toStored(layer, Number(value.replace(',', '.')), temp) ?? 'out-of-range';
}

export function watchFormBody(form: WatchForm, temp: Temp): FormResult {
  const {layer} = form;
  if (!isWatchLayer(layer)) return {ok: false, field: 'layer', error: 'required'};
  const op = WATCH_OPS.find(option => option === form.op);
  if (op === undefined) return {ok: false, field: 'op', error: 'required'};
  const a = parseValue(form.a, layer, temp);
  if (typeof a !== 'number') return {ok: false, field: 'a', error: a};
  if (op !== 'between') return {ok: true, body: {layer, op, a, b: null}};
  const b = parseValue(form.b, layer, temp);
  if (typeof b !== 'number') return {ok: false, field: 'b', error: b};
  if (a >= b) return {ok: false, field: 'b', error: 'order'};
  return {ok: true, body: {layer, op, a, b}};
}

export function watchForm({layer, op, a, b}: WatchBody, temp: Temp) {
  return {
    layer,
    op,
    a: String(fromStored(layer, a, temp)),
    b: b === null ? '' : String(fromStored(layer, b, temp)),
  };
}

export function formUnchanged(form: WatchForm, watch: WatchBody, temp: Temp): boolean {
  // Compare display text, not the numbers obtained by re-parsing rounded display values.
  const shown = watchForm(watch, temp);
  return form.layer.trim() === shown.layer && form.op.trim() === shown.op &&
    form.a.trim() === shown.a && form.b.trim() === shown.b;
}
