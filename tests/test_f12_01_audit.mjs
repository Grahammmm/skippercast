// F12-01 / SCA-529: offline controls, not a product fix. The default Node suite
// qualifies the contract with a synthetic composer. Run this file directly with
// --baseline to apply the same assertions to the unchanged chat component; a
// confirmed gap is a failure in that opt-in replay, not an expected CI result.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {setImmediate as drain} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';
import test from 'node:test';
import {buildSync} from 'esbuild';
import {CHAT_COPY as copy, CHAT_TIMEOUT_MS} from '../web/advisor/copy.ts';

const baseline = process.argv.includes('--baseline');
const upload = '/api/advisor/web/upload';
const message = '/api/advisor/web/message';
const photo = new File(['synthetic photo bytes'], 'fixture.jpg', {type: 'image/jpeg'});
const mediaId = 'fixture-media-from-upload';
const caption = 'Synthetic caption';
const post = (path, body) => ({method: 'POST', path, body});
const photoPost = post(upload, [photo.name, photo.type, await photo.text()]);
const photoMessage = post(message, {text: caption, media_ids: [mediaId]});

// Reference control: selection is only a local File; the upload stub never
// resolves on its own in the timeout case. This is not production UI code.
function reference({fetch, setTimeout, clearTimeout}) {
  let open = true, file, text = '', busy = false;
  return () => ({
    open, hasPhoto: Boolean(file), pickerDisabled: busy, sendDisabled: busy || !(text || file),
    pick: picked => { file = picked; }, remove: () => { file = undefined; },
    close: () => { open = false; }, type: value => { text = value; },
    async send() {
      busy = true;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
      try {
        const payload = {text};
        if (file) {
          const form = new FormData();
          form.append('file', file);
          const response = await fetch(upload, {method: 'POST', body: form, signal: controller.signal});
          payload.media_ids = [(await response.json()).media_id];
        }
        await fetch(message, {method: 'POST', body: JSON.stringify(payload)});
        file = undefined;
        text = '';
      } catch (error) {
        if (!controller.signal.aborted) throw error;
      } finally { clearTimeout(timer); busy = false; }
    },
  });
}

const require = createRequire(import.meta.url);
const source = fileURLToPath(new URL('../web/advisor/chat.tsx', import.meta.url));
let compiled;
if (baseline) {
  const bytes = readFileSync(source);
  console.log(`F12-01 read-only replay; chat.tsx sha256=${createHash('sha256').update(bytes).digest('hex')}`);
  compiled = buildSync({stdin: {contents: bytes.toString(), resolveDir: fileURLToPath(new URL('../web/advisor/', import.meta.url)), loader: 'tsx', sourcefile: 'chat.tsx'},
    bundle: true, write: false, format: 'cjs', platform: 'node', external: ['preact', 'preact/*'], jsx: 'automatic', jsxImportSource: 'preact'}).outputFiles[0].text;
}

// Render the real TSX and call its rendered handlers with deterministic hooks.
// No DOM, browser/server integration, or transport can be reached from this replay.
function composer(deps) {
  const slots = [], effects = [], storage = new Map();
  let cursor;
  const hooks = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
    },
    useRef: initial => hooks.useState(() => ({current: initial}))[0],
    useEffect(fn, values = []) {
      const i = cursor++, previous = slots[i];
      if (!previous || values.some((value, j) => !Object.is(value, previous.values[j]))) {
        effects.push(() => { previous?.cleanup?.(); slots[i] = {values, cleanup: fn()}; });
      }
    },
  };
  const module = {exports: {}};
  runInNewContext(compiled, {...deps, module, FormData, AbortController,
    requestAnimationFrame: callback => callback(),
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
    require(id) {
      if (id === 'preact/hooks') return hooks;
      if (id === 'preact' || id === 'preact/jsx-runtime') return require(id);
      throw new Error(`Unexpected module: ${id}`);
    },
  });
  function* nodes(node) {
    if (Array.isArray(node)) { for (const item of node) yield* nodes(item); }
    else if (node?.props) { yield node; yield* nodes(node.props.children); }
  }
  return () => {
    cursor = 0;
    const tree = module.exports.Chat({defaultOpen: true});
    for (const effect of effects.splice(0)) effect();
    if (tree.type === 'button') return {open: false};
    const find = predicate => [...nodes(tree)].find(predicate)?.props;
    const button = name => find(n => n.type === 'button' && (n.props.children === name || n.props['aria-label'] === name));
    const picker = find(n => n.type === 'input' && n.props.type === 'file');
    const send = button(copy.send), remove = button(copy.removePhoto);
    return {
      open: true, hasPhoto: Boolean(remove), pickerDisabled: Boolean(picker.disabled), sendDisabled: Boolean(send.disabled),
      pick: file => picker.onChange({currentTarget: {files: [file], value: file.name}}),
      remove: () => remove.onClick(), close: () => button(copy.close).onClick(),
      type: value => find(n => n.type === 'textarea').onInput({currentTarget: {value}}),
      send: () => send.onClick(),
    };
  };
}

function fixture(t, stalled = false) {
  t.mock.timers.enable({apis: ['setTimeout']});
  const calls = [];
  const view = (baseline ? composer : reference)({setTimeout, clearTimeout,
    async fetch(path, {method, body, signal}) {
      const call = {method, path};
      calls.push(call);
      if (path === upload) {
        const picked = body.get('file');
        call.body = [picked.name, picked.type, await picked.text()];
        if (stalled) return new Promise((_, reject) => {
          const abort = () => reject(signal.reason);
          if (signal?.aborted) abort();
          else signal?.addEventListener('abort', abort, {once: true});
        });
        return Response.json({media_id: mediaId});
      }
      assert.equal(path, message, 'unexpected request intercepted offline');
      call.body = JSON.parse(body);
      return Response.json({replies: []});
    },
  });
  return {view, calls, async pick() { void view().pick(photo); await drain(); }};
}

for (const action of ['remove', 'close']) {
  test(`F12-01: pick then ${action} without Send makes zero requests`, async t => {
    const {view, calls, pick} = fixture(t);
    await pick();
    assert.equal(view().hasPhoto, true, 'a selection is shown locally');
    const afterPick = calls.slice();
    view()[action]();
    await drain();
    assert.equal(action === 'close' ? view().open : view().hasPhoto, false);
    assert.deepEqual({afterPick, afterAction: calls}, {afterPick: [], afterAction: []});
  });
}

test('F12-01: Send uploads once and sends the returned media ID', async t => {
  const {view, calls, pick} = fixture(t);
  await pick();
  const beforeSend = calls.slice();
  view().type(caption);
  assert.equal(view().sendDisabled, false);
  void view().send();
  await drain();
  assert.deepEqual({beforeSend, afterSend: calls.slice(beforeSend.length)}, {beforeSend: [], afterSend: [photoPost, photoMessage]});
});

test('F12-01: a hung upload times out without sending or locking the composer', async t => {
  const {view, calls, pick} = fixture(t, true);
  await pick();
  const beforeSend = calls.slice();
  view().type(caption);
  const sendWasEnabled = !view().sendDisabled;
  if (sendWasEnabled) void view().send();
  await drain();
  const whilePending = calls.slice(beforeSend.length);
  t.mock.timers.tick(CHAT_TIMEOUT_MS);
  await drain();
  const afterTimeout = calls.slice(beforeSend.length);
  const {pickerDisabled} = view();
  if (view().hasPhoto) view().remove();
  const followup = 'Next synthetic message';
  view().type(followup);
  const recovered = !view().sendDisabled;
  if (recovered) void view().send();
  await drain();
  assert.deepEqual({beforeSend, sendWasEnabled, whilePending, afterTimeout, pickerDisabled, recovered,
    afterFollowup: calls.slice(beforeSend.length + afterTimeout.length)},
    {beforeSend: [], sendWasEnabled: true, whilePending: [photoPost], afterTimeout: [photoPost], pickerDisabled: false,
      recovered: true, afterFollowup: [post(message, {text: followup})]});
});
