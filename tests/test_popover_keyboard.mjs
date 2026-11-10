// RF0834-7: Escape closes the active basis disclosure and returns focus to its own summary.
// The real bundled Popover supplies the key handler (read from its rendered VNode); the DOM around it,
// details.open, direct-summary focus and event bubbling are modelled explicitly (no browser, offline).
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;

async function load() {
  const dir = await mkdtemp(join(tmpdir(), 'popover-keyboard-'));
  const out = join(dir, 'm.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {Popover} from './web/ui/Popover.tsx';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact'});
  return import(pathToFileURL(out).href);
}

const {Popover} = await load();

const focus = {current: null};
let calls = [];

function node(tagName, parent, extra = {}) {
  const n = {tagName, parentNode: parent ?? null, children: [], focus() { focus.current = n; calls.push(['focus', n.name]); }, ...extra};
  parent?.children.push(n);
  return n;
}

// A <details> whose keydown handler is the one the real Popover renders.
function disclosure(parent, name, props = {}, {open = true} = {}) {
  const vnode = Popover({children: 'Body', ...props});
  const details = node('DETAILS', parent, {name, open, handler: vnode.props.onKeyDown});
  const summary = node('SUMMARY', details, {name: `${name}-summary`});
  const body = node('DIV', details, {name: `${name}-body`});
  const link = node('A', body, {name: `${name}-link`});
  return {details, summary, body, link};
}

function press(target, key, {prevented = false} = {}) {
  const event = {
    key, target, currentTarget: null, defaultPrevented: prevented, propagationStopped: false, stopped: 0,
    preventDefault() { this.defaultPrevented = true; this.prevented = (this.prevented ?? 0) + 1; },
    stopPropagation() { this.propagationStopped = true; this.stopped += 1; },
  };
  for (let n = target; n; n = n.parentNode) {
    if (!n.handler) continue;
    event.currentTarget = n;
    n.handler(event);
    if (event.propagationStopped) break;
  }
  return event;
}

function fresh() {
  focus.current = null;
  calls = [];
  const dialog = node('DIALOG', null, {name: 'dialog', escapes: 0, handler(e) { if (e.key === 'Escape' && !e.defaultPrevented) this.escapes += 1; }});
  return dialog;
}

test('escape_from_summary_closes_and_keeps_trigger_focus', () => {
  const dialog = fresh();
  const a = disclosure(dialog, 'a');
  const event = press(a.summary, 'Escape');
  assert.equal(a.details.open, false, 'the disclosure closed');
  assert.equal(focus.current, a.summary, 'focus is on its own summary');
  assert.equal(calls.filter(c => c[0] === 'focus').length, 1);
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.stopped, 1, 'propagation stopped once');
  assert.equal(dialog.escapes, 0, 'the enclosing dialog was not dismissed');
});

test('escape_from_source_link_returns_to_own_summary', () => {
  const dialog = fresh();
  const a = disclosure(dialog, 'a');
  const b = disclosure(dialog, 'b');
  press(a.link, 'Escape');
  assert.equal(a.details.open, false);
  assert.equal(b.details.open, true, 'a sibling disclosure is untouched');
  assert.equal(focus.current, a.summary, 'focus goes to the owning summary, not a sibling');
  assert.equal(dialog.escapes, 0);
  for (const props of [{iconOnly: true}, {sources: false}, {sources: '/elsewhere', summary: 'Why'}, {summary: ''}]) {
    const d = disclosure(dialog, 'c', props);
    focus.current = null;
    press(d.link, 'Escape');
    assert.equal(d.details.open, false, JSON.stringify(props));
    assert.equal(focus.current, d.summary, JSON.stringify(props));
  }
});

test('escape_closed_or_prevented_is_inert', () => {
  const dialog = fresh();
  const closed = disclosure(dialog, 'closed', {}, {open: false});
  const closedEvent = press(closed.summary, 'Escape');
  assert.equal(closed.details.open, false);
  assert.equal(focus.current, null, 'a closed disclosure moves no focus');
  assert.ok(!closedEvent.prevented && !closedEvent.stopped, 'nothing prevented or stopped');
  assert.equal(dialog.escapes, 1, 'the dialog still sees an Escape nobody handled');

  const open = disclosure(dialog, 'open');
  const handled = press(open.summary, 'Escape', {prevented: true});
  assert.equal(open.details.open, true, 'an already-handled Escape leaves the disclosure open');
  assert.equal(focus.current, null);
  assert.ok(!handled.prevented && !handled.stopped);
});

test('other_keys_keep_native_details_behavior', () => {
  const dialog = fresh();
  const a = disclosure(dialog, 'a');
  for (const key of ['Enter', ' ', 'Tab', 'ArrowDown', 'a']) {
    const event = press(a.summary, key);
    assert.equal(a.details.open, true, key);
    assert.ok(!event.prevented && !event.stopped, `${JSON.stringify(key)} neither prevented nor stopped`);
  }
  assert.equal(focus.current, null);
});

test('nested_disclosure_escape_only_closes_innermost', () => {
  const dialog = fresh();
  const outer = disclosure(dialog, 'outer');
  const inner = disclosure(outer.body, 'inner');
  press(inner.link, 'Escape');
  assert.equal(inner.details.open, false, 'the innermost closed');
  assert.equal(outer.details.open, true, 'the outer stays open');
  assert.equal(focus.current, inner.summary, 'focus is on the inner summary, not the outer one');
  assert.equal(dialog.escapes, 0);

  // A second Escape, now from the outer disclosure's own content, closes the outer one.
  press(outer.link, 'Escape');
  assert.equal(outer.details.open, false);
  assert.equal(focus.current, outer.summary);
  assert.equal(dialog.escapes, 0);

  // With nothing open left, Escape reaches the enclosing dialog.
  press(outer.summary, 'Escape');
  assert.equal(dialog.escapes, 1);
});

test('escape_keeps_focus_an_inner_handler_already_moved_out', () => {
  const dialog = fresh();
  const a = disclosure(dialog, 'a');
  const elsewhere = node('BUTTON', dialog, {name: 'elsewhere'});
  const doc = {body: node('BODY', null, {name: 'body'}), activeElement: elsewhere};
  a.details.ownerDocument = doc;
  a.details.contains = n => { for (let x = n; x; x = x.parentNode) if (x === a.details) return true; return false; };
  press(a.link, 'Escape');
  assert.equal(a.details.open, false, 'the disclosure still closes');
  assert.equal(calls.filter(c => c[0] === 'focus').length, 0, 'focus stays where the inner handler put it');
  assert.equal(dialog.escapes, 0);

  doc.activeElement = a.link;
  a.details.open = true;
  press(a.link, 'Escape');
  assert.equal(focus.current, a.summary, 'focus still inside goes back to the summary');
});
