// F04-10: drive the real route, collector and chat UI across the server deadline.
// Only the engine, storage and browser transport are synthetic; no rows or network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
import test from 'node:test';
import {setImmediate as drain} from 'node:timers/promises';
import {transformSync} from 'esbuild';
import {h, render} from 'preact';
import {act} from 'preact/test-utils';
import {CHAT_COPY} from '../web/advisor/copy.ts';

const origin = 'https://fixture.invalid';
const path = '/api/advisor/web/message';
const routeUrl = new URL('../server/routes/advisor.ts', import.meta.url).href;
const chatUrl = new URL('../web/advisor/chat.tsx', import.meta.url).href;
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: [origin]};

// Keep the actual request handler and send/close contract. Substitute only the
// turn driver so tests select when each send happens without running an engine.
const stubs = {
  '../advisor/inbound.ts': 'export const storeInbound = () => "fixture-turn", dispatchInbound = null, storeUpload = null;',
  '../advisor/consumer.ts': 'export const runInline = (env, _id, {channel}) => env.fixtureTurn(channel);',
};
const hooks = registerHooks({
  resolve(specifier, context, next) {
    if (context.parentURL === routeUrl && Object.hasOwn(stubs, specifier)) {
      return {url: `data:text/javascript,${encodeURIComponent(stubs[specifier])}`, shortCircuit: true};
    }
    return next(specifier, context);
  },
  load(url, context, next) {
    if (url !== chatUrl) return next(url, context);
    const source = transformSync(readFileSync(new URL(url), 'utf8'), {loader: 'tsx', format: 'esm', jsx: 'automatic', jsxImportSource: 'preact'}).code;
    return {format: 'module', source, shortCircuit: true};
  },
});
const {advisorPublic, webChat} = await import(routeUrl);
const {Chat} = await import(chatUrl);
hooks.deregister();

// Small in-memory DOM for the real Preact render/event cycle.
class Element {
  constructor(name, data) {
    Object.assign(this, {localName: name, nodeType: data === undefined ? 1 : 3, data,
      childNodes: [], parentNode: null, attrs: {}, listeners: {}, value: ''});
  }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  insertBefore(child, ref) {
    child.remove();
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, child);
    child.parentNode = this;
  }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  removeEventListener(type) { delete this.listeners[type]; }
  focus() {}
  fire(type) { this.listeners[type].call(this, {type, currentTarget: this}); }
}
globalThis.document = {
  createElement: name => new Element(name),
  createElementNS: (_, name) => new Element(name),
  createTextNode: data => new Element('#text', String(data)),
};
const nodes = root => [root, ...root.childNodes.flatMap(nodes)];
const text = node => node.data ?? node.childNodes.map(text).join('');
const early = {id: 'early', text: 'Early fixture reply', mediaKeys: ['advisor/derived/demo/public.jpg', 'advisor/private/demo.jpg']};
const late = {id: 'late', text: 'Late fixture reply'};
const wireReply = {id: early.id, text: early.text, links: [], media: ['/media/demo.jpg']};

async function submit(t, respond, afterClick) {
  const root = new Element('div');
  const posts = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, path);
    assert.equal(init.method, 'POST');
    posts.push(JSON.parse(init.body));
    return respond(new Request(origin + path, {...init, headers: {...init.headers, Origin: origin}}));
  });
  await act(() => render(h(Chat, {defaultOpen: true}), root));
  const input = nodes(root).find(n => n.localName === 'textarea');
  input.value = 'Synthetic question';
  await act(() => input.fire('input'));
  await act(async () => {
    nodes(root).find(n => n.localName === 'button' && text(n) === CHAT_COPY.send).fire('click');
    await afterClick?.();
    await drain();
  });
  assert.deepEqual(posts, [{text: 'Synthetic question'}], 'one submit, no automatic repeat');
  return nodes(root).filter(n => n.localName === 'p' && [early.text, late.text].includes(text(n)) || n.attrs.role === 'status' || n.localName === 'img')
    .map(n => n.localName === 'img' ? n.attrs.src : text(n));
}

for (const [name, hasEarly, timesOut] of [['partial timeout', true, true], ['fast turn', true, false], ['empty timeout', false, true]]) {
  test(`F04-10: ${name}`, {timeout: 3000}, async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    t.mock.method(console, 'warn', () => {});
    const started = Promise.withResolvers(), finish = Promise.withResolvers();
    const sent = [], tail = [];
    const env = {TEXT_ADVISOR_ENABLED: 'true',
      DB: {prepare: () => ({bind: () => ({first: async () => null})})},
      async fixtureTurn(channel) {
        if (hasEarly) sent.push(await channel.send(early));
        started.resolve();
        if (timesOut) {
          await finish.promise;
          sent.push(await channel.send(late));
        }
      },
    };
    const replied = Promise.withResolvers();
    let response, payload;
    const visible = await submit(t, async request => {
      try {
        response = await advisorPublic.fetch(request, env, {waitUntil: work => tail.push(work)});
        payload = await response.clone().json();
        return response;
      } finally { replied.resolve(); }
    }, async () => {
      await started.promise;
      if (timesOut) t.mock.timers.tick(webChat.timeoutMs);
      await replied.promise;
      finish.resolve();
      await Promise.all(tail);
    });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.deepEqual(sent, [
      ...(hasEarly ? [{providerId: early.id, status: 'sent'}] : []),
      ...(timesOut ? [{providerId: null, status: 'failed', error: 'web-closed'}] : []),
    ], 'no late reply is marked sent');
    assert.equal(tail.length, Number(timesOut), 'only timed-out work continues in waitUntil');
    assert.deepEqual(payload, {replies: hasEarly ? [wireReply] : [],
      ...(timesOut ? {pending: true} : {contact: {language: 'en', linked: false}})});
    assert.deepEqual(visible, [...(hasEarly ? [early.text, wireReply.media[0]] : []), timesOut ? CHAT_COPY.pending : '']);
  });
}

// Independent client control: a pending response carrying a reply must render
// it once, above the notice, even if the route itself was unchanged and red.
test('F04-10: chat displays a reply carried by a pending response', async t => {
  assert.deepEqual(await submit(t, () => Response.json({replies: [wireReply], pending: true})),
    [early.text, wireReply.media[0], CHAT_COPY.pending]);
});
