// SP-17-v1: complete Sheet component, installed Preact hooks + renderer, inert elements.
import assert from 'node:assert/strict';
import test, {after, before} from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import net from 'node:net';
import http from 'node:http';
import https from 'node:https';
import tls from 'node:tls';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const fixture = JSON.parse(await readFile(new URL('./fixtures/sp1710_sheet_pointer_owner/gestures.json', import.meta.url), 'utf8'));
let component;
const restore = [];
function replace(object, key, value) {
  const descriptor = Object.getOwnPropertyDescriptor(object, key);
  restore.push(() => descriptor ? Object.defineProperty(object, key, descriptor) : delete object[key]);
  Object.defineProperty(object, key, {configurable: true, writable: true, value});
}
before(async () => {
  // Installed before product import. No source/model/store acquisition is permitted.
  const denied = () => { throw new Error('SP1710 offline sentinel: external I/O forbidden'); };
  for (const key of ['fetch', 'WebSocket', 'XMLHttpRequest', 'localStorage', 'sessionStorage']) replace(globalThis, key, denied);
  for (const [object, keys] of [[net, ['connect', 'createConnection']], [net.Socket.prototype, ['connect']],
    [tls, ['connect']], [http, ['request', 'get']], [https, ['request', 'get']]]) {
    for (const key of keys) replace(object, key, denied);
  }
  replace(globalThis, 'getComputedStyle', () => ({transform: 'fixture-matrix'}));
  replace(globalThis, 'DOMMatrixReadOnly', class {m42 = fixture.baseTranslation;});
  const out = join(await mkdtemp(join(tmpdir(), 'sp1710-')), 'sheet.mjs');
  // Virtual entry only re-exports complete real modules; no product substitutions.
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents:
    "export {Sheet} from './web/ui/Sheet.tsx'; export {h, options} from 'preact'; export {render} from 'preact-render-to-string';"},
    bundle: true, platform: 'node', format: 'esm', outfile: out,
    jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent'});
  component = await import(pathToFileURL(out).href);
});
after(() => { for (const undo of restore.reverse()) undo(); });

function mount(detent = 'peek') {
  const commits = [], captured = [];
  const sheet = {style: {transition: '', transform: ''}, offsetHeight: fixture.sheetHeight};
  const handle = {dataset: {}, closest: selector => {assert.equal(selector, '.ui-sheet'); return sheet;},
    setPointerCapture: id => captured.push(id)};
  const {Sheet, h, render, options} = component;
  const prior = options.vnode;
  let handlers;
  options.vnode = vnode => {
    prior?.(vnode);
    if (vnode.type === 'button' && vnode.props.class === 'ui-sheet-handle') handlers = vnode.props;
  };
  let html;
  try { html = render(h(Sheet, {label: 'Synthetic sheet', detent, onDetent: value => commits.push(value), children: 'Synthetic body'})); }
  finally { options.vnode = prior; }
  assert.match(html, /class="ui-sheet-handle"/);
  assert.equal(typeof handlers.onPointerDown, 'function');
  const pointer = (kind, pointerId = 1, clientY = 300, button = 0) => {
    handlers[`onPointer${kind}`]({pointerId, clientY, button, currentTarget: handle});
  };
  const click = () => handlers.onClick({currentTarget: handle});
  const key = value => {
    let prevented = false;
    handlers.onKeyDown({key: value, preventDefault() {prevented = true;}});
    return prevented;
  };
  return {sheet, handle, commits, captured, pointer, click, key};
}
function clean(m) {assert.deepEqual(m.sheet.style, {transition: '', transform: ''});}
function ordinary(m) {m.pointer('Down'); m.pointer('Move', 1, fixture.ownerEndY); m.pointer('Up', 1, fixture.ownerEndY);}
// Select by registration rather than Node's name filter: excluded cases are not skips.
const selector = process.env.SP1710_SELECTOR ?? 'all';
if (!['all', 'A1', 'control'].includes(selector)) throw new Error('Unknown SP1710_SELECTOR');
function check(id, name, body) {if (selector === 'all' || selector === id) test(name, body);}

check('A1', 'A1: interleaved pointer-2 down cannot replace pointer-1 origin', () => {
  const m = mount();
  m.pointer('Down', fixture.owner.pointerId, fixture.owner.clientY);
  m.pointer('Move', 1, fixture.ownerEndY);
  m.pointer('Down', fixture.interloper.pointerId, fixture.interloper.clientY);
  m.pointer('Up', 1, fixture.ownerEndY);
  assert.deepEqual(m.commits, ['half'], 'SP1710_ORIGIN: owner release must select half, not full');
  assert.deepEqual(m.captured, [1]);
  clean(m);
});
check('control', 'The ordinary pointer-1 drag without interleaving still selects half and clears temporary styles', () => {
  const m = mount(); ordinary(m);
  assert.deepEqual(m.commits, ['half']); clean(m);
  assert.equal(m.handle.dataset.dragged, 'true');
  m.click(); assert.deepEqual(m.commits, ['half']);
  assert.equal(m.handle.dataset.dragged, undefined);
});
check('A2', 'A2: non-owner move, up and cancel are inert; owner still finishes', () => {
  for (const kind of ['Move', 'Up', 'Cancel']) {
    const m = mount(); m.pointer('Down'); m.pointer('Move', 1, 260);
    const style = {...m.sheet.style};
    m.pointer(kind, 2, 650);
    assert.deepEqual(m.sheet.style, style, kind);
    assert.deepEqual(m.commits, [], kind);
    assert.deepEqual(m.captured, [1], kind);
    m.pointer('Move', 1, 220); m.pointer('Up', 1, 220);
    assert.deepEqual(m.commits, ['half'], kind); clean(m);
    m.click(); assert.deepEqual(m.commits, ['half'], 'drag click remains suppressed');
  }
  const m = mount(); m.pointer('Down'); m.pointer('Down', 1, 600);
  m.pointer('Move', 1, 220); m.pointer('Up', 1, 220);
  assert.deepEqual(m.commits, ['half'], 'duplicate owner down is also ignored');
});
check('A3', 'A3: owner cancellation cleans up without commit and a fresh pointer can drag or tap', () => {
  const m = mount(); m.pointer('Down'); m.pointer('Move', 1, 220); m.pointer('Cancel', 1, 220);
  clean(m); assert.deepEqual(m.commits, []); assert.equal(m.handle.dataset.dragged, undefined);
  m.pointer('Move', 1, 0); m.pointer('Up', 1, 0); clean(m); assert.deepEqual(m.commits, []);
  m.pointer('Down', 2, 300); m.pointer('Move', 2, 220); m.pointer('Up', 2, 220);
  assert.deepEqual(m.captured, [1, 2]); assert.deepEqual(m.commits, ['half']); clean(m);
  // A stray cancellation cannot remove a completed drag's one-click suppression.
  m.pointer('Cancel', 1, 0); m.click(); assert.deepEqual(m.commits, ['half']);
  m.pointer('Down', 3, 300); m.pointer('Up', 3, 300); m.click();
  assert.deepEqual(m.commits, ['half', 'half']);
  const tap = mount(); tap.pointer('Down'); tap.pointer('Move', 1, 280); tap.pointer('Cancel');
  tap.pointer('Down', 2); tap.pointer('Up', 2); tap.click(); assert.deepEqual(tap.commits, ['half']);
});
check('A4', 'A4: drag thresholds, clamping, tap suppression, clicks and keyboard retain results', () => {
  for (const row of fixture.thresholds) {
    const m = mount(row.from); m.pointer('Down'); m.pointer('Move', 1, 300 + row.dy);
    assert.equal(m.sheet.style.transform, `translateY(${Math.max(0, fixture.baseTranslation + row.dy)}px)`);
    m.pointer('Up', 1, 300 + row.dy); clean(m);
    assert.deepEqual(m.commits, row.to === row.from ? [] : [row.to], JSON.stringify(row));
  }
  for (const [dy, suppressed] of [[11, false], [12, true], [-11, false], [-12, true]]) {
    const m = mount(); m.pointer('Down'); m.pointer('Move', 1, 300 + dy); m.pointer('Up', 1, 300 + dy); m.click();
    assert.deepEqual(m.commits, suppressed ? [] : ['half']); clean(m);
  }
  for (const [from, to] of [['peek', 'half'], ['half', 'full'], ['full', 'peek']]) {
    const m = mount(from); m.click(); assert.deepEqual(m.commits, [to]);
  }
  for (const [from, key, to] of [['peek', 'ArrowUp', 'half'], ['half', 'ArrowUp', 'full'],
    ['full', 'ArrowUp', 'full'], ['full', 'ArrowDown', 'half'], ['half', 'ArrowDown', 'peek'],
    ['peek', 'ArrowDown', 'peek'], ['full', 'Home', 'peek'], ['peek', 'End', 'full'], ['half', 'Escape', 'peek']]) {
    const m = mount(from); assert.equal(m.key(key), true); assert.deepEqual(m.commits, from === to ? [] : [to]);
  }
  // Enter/Space use the real button's native click, not a duplicate key handler.
  for (const key of ['Enter', ' ', 'Tab', 'x']) {const m = mount(); assert.equal(m.key(key), false); assert.deepEqual(m.commits, []);}
  const m = mount(); m.pointer('Down', 1, 300, 2); m.pointer('Move', 1, 100); m.pointer('Up', 1, 100);
  assert.deepEqual(m.captured, []); assert.deepEqual(m.commits, []); clean(m);
});
