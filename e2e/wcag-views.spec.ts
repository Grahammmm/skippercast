// BF-wcag: a WCAG 2.1 AA gate over every app view (web/state.ts APP_VIEWS, so a new view is covered without editing this
// file) at the phone and laptop projects. Each view fails on any WCAG 2.1 A/AA axe violation of any impact, any keyboard
// focus stop without a visible indicator, and any control smaller than 24×24 CSS px (WCAG 2.5.8; inline links inside a
// paragraph are exempt). The only waivers are e2e/wcag-known.json entries, each with a reason and an open `#<n>` ref;
// an entry that no longer matches anything fails as stale. Results land in AXE_DIR beside checkA11y's (axe-summary.ts).
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import type {Page} from '@playwright/test';
import {APP_VIEWS} from '../web/state.ts';
import {AXE_DIR, expect, test} from './fixtures.ts';

type Kind = 'axe' | 'focus' | 'target';
interface Finding {kind: Kind; rule: string; selector: string}
interface Known extends Finding {view: string; project: string; reason: string; ref: string}
const KINDS: readonly string[] = ['axe', 'focus', 'target'];
const MIN = 24, MAX_STOPS = 40;
/** A heading each view shows once rendered (also in its 503 forecast state); a view not listed waits for any h1/h2. */
const HEADINGS: Record<string, string> = {coast: 'Where to look', conditions: 'Conditions', history: 'Recorded history', fleet: 'Fleet', reports: 'Reports'};

/** Problems with the known list itself: every field present, a known kind, and `ref` an open PR or issue as `#<n>`. */
export function knownProblems(list: unknown): string[] {
  if (!Array.isArray(list)) return ['wcag-known.json is not an array'];
  return list.flatMap((e: Partial<Known>, i) => {
    const bad: string[] = (['view', 'project', 'kind', 'rule', 'selector', 'reason'] as const).filter(k => typeof e?.[k] !== 'string' || !e[k]!.trim());
    if (!KINDS.includes(String(e?.kind))) bad.push('kind');
    if (typeof e?.ref !== 'string' || !/^#\d+$/.test(e.ref)) bad.push('ref');
    return bad.length ? [`entry ${i}: bad ${[...new Set(bad)].join(', ')}`] : [];
  });
}

/** Exact match on (view, project, kind, rule, selector): findings not waived, and this case's entries that matched nothing. */
export function compare(found: Finding[], known: Known[], view: string, project: string): {unexpected: Finding[]; stale: Known[]} {
  const mine = known.filter(k => k.view === view && k.project === project);
  const same = (a: Finding, b: Finding) => a.kind === b.kind && a.rule === b.rule && a.selector === b.selector;
  return {unexpected: found.filter(f => !mine.some(k => same(f, k))), stale: mine.filter(k => !found.some(f => same(f, k)))};
}

// In-page helpers as source text, so the bundler cannot rename what the page runs. `__wcagDescribe` names an element
// stably: tag#id, or tag.classes[aria-label], prefixed by its parent's name when the element has neither.
const HELPERS = `window.__wcagDescribe = function d(el) {
  if (!el || el === document.body || el === document.documentElement) return 'body';
  const tag = el.tagName.toLowerCase(), label = el.getAttribute('aria-label');
  if (el.id) return tag + '#' + el.id;
  const own = Array.from(el.classList).map(c => '.' + c).join('') + (label ? '[aria-label="' + label + '"]' : '') + (el.type === 'checkbox' || el.type === 'radio' ? '[type=' + el.type + ']' : '');
  return own && (el.classList.length || label) ? tag + own : d(el.parentElement || el.getRootNode().host) + ' > ' + tag + own;
};
window.__wcagShown = el => !el.closest('[aria-hidden="true"], [inert]') && el.checkVisibility({visibilityProperty: true}) && el.getClientRects().length > 0;
window.__wcagAll = (sel, root = document) => [...root.querySelectorAll(sel), ...[...root.querySelectorAll('*')].flatMap(e => e.shadowRoot ? window.__wcagAll(sel, e.shadowRoot) : [])];
window.__wcagActive = () => { let el = document.activeElement; while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement; return el; };`;

/** Every visible control under 24×24 px, except inline links inside a paragraph and visually hidden (≤1 px) skip links. */
export async function smallTargets(page: Page): Promise<Finding[]> {
  await page.evaluate(HELPERS);
  return page.evaluate(({min}) => {
    const w = window as unknown as {__wcagDescribe: (e: Element) => string; __wcagShown: (e: Element) => boolean; __wcagAll: (s: string) => Element[]};
    const out = new Map<string, {kind: 'target'; rule: string; selector: string}>();
    for (const el of w.__wcagAll('button, a[href], input:not([type=hidden]), select, [role=button], [role=switch], [role=tab]')) {
      if (!w.__wcagShown(el) || (el.matches('a') && el.closest('p'))) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1 || (r.width >= min && r.height >= min)) continue;
      const selector = w.__wcagDescribe(el);
      out.set(selector, {kind: 'target', rule: 'target-size', selector});
    }
    return [...out.values()];
  }, {min: MIN});
}

/** Tab through the page (≤40 stops, or until focus returns to a stop already seen or leaves the document): each stop must be
 *  shown and have an outline ≥1 px or a box-shadow; the same element twice in a row is a focus trap. */
export async function focusWalk(page: Page): Promise<Finding[]> {
  await page.evaluate(HELPERS);
  await page.evaluate(() => { (window as unknown as {__wcagSeen: Element[]}).__wcagSeen = []; (document.activeElement as HTMLElement | null)?.blur(); });
  const out = new Map<string, Finding>();
  for (let stop = 0; stop < MAX_STOPS; stop++) {
    await page.keyboard.press('Tab');
    const s = await page.evaluate(() => {
      const w = window as unknown as {__wcagDescribe: (e: Element) => string; __wcagShown: (e: Element) => boolean; __wcagSeen: Element[]; __wcagActive: () => Element | null};
      const el = w.__wcagActive();   // inside an open shadow root (CoastMarkup), the focused element, not its host
      if (!el || el === document.body) return null;   // focus left the document
      const seen = w.__wcagSeen.indexOf(el), last = w.__wcagSeen.at(-1) === el;
      w.__wcagSeen.push(el);
      const cs = getComputedStyle(el), ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 1) || cs.boxShadow !== 'none';
      return {selector: w.__wcagDescribe(el), seen: seen >= 0, trap: last, shown: w.__wcagShown(el), ring};
    });
    if (!s) break;
    if (s.trap) { out.set(`trap ${s.selector}`, {kind: 'focus', rule: 'focus-trap', selector: s.selector}); break; }
    if (s.seen) break;
    if (!s.shown) out.set(`hidden ${s.selector}`, {kind: 'focus', rule: 'focus-not-visible', selector: s.selector});
    else if (!s.ring) out.set(`ring ${s.selector}`, {kind: 'focus', rule: 'focus-indicator', selector: s.selector});
  }
  return [...out.values()];
}

const known: Known[] = JSON.parse(readFileSync(join(import.meta.dirname, 'wcag-known.json'), 'utf8'));

test('the known list is well-formed: every entry has a kind, a reason and an open #<n> ref', () => {
  expect(knownProblems(known)).toEqual([]);
});

for (const view of APP_VIEWS) {
  test(`WCAG 2.1 AA: ${view} view`, async ({page, v2, pageErrors}, info) => {
    void pageErrors;
    await v2.open('app', {view, region: 'morro-bay'});
    const heading = HEADINGS[view];
    await expect(heading ? page.getByRole('heading', {name: heading, exact: true}) : page.locator('h1, h2').first()).toBeVisible();
    const axe = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).exclude('canvas').analyze();
    const found: Finding[] = axe.violations.flatMap(v => v.nodes.map(n => ({kind: 'axe' as const, rule: v.id, selector: n.target.join(' ')})));
    found.push(...await smallTargets(page), ...await focusWalk(page));
    const counts = (kind: Kind) => [...new Set(found.filter(f => f.kind === kind).map(f => f.rule))]
      .map(id => ({id, impact: axe.violations.find(v => v.id === id)?.impact ?? null, nodes: found.filter(f => f.rule === id).length}));
    mkdirSync(AXE_DIR, {recursive: true});
    writeFileSync(join(AXE_DIR, `${info.project.name}-wcag-${view}.json`), JSON.stringify({page: `wcag-${view}`, project: info.project.name, url: page.url(),
      violations: [...counts('axe'), ...counts('focus'), ...counts('target')], incomplete: axe.incomplete.map(v => ({id: v.id, impact: v.impact ?? null, nodes: v.nodes.length}))}, null, 1));
    const {unexpected, stale} = compare(found, known, view, info.project.name);
    expect(unexpected, `WCAG findings on ${view} (fix them, or list them in e2e/wcag-known.json with a reason and #<n>)`).toEqual([]);
    expect(stale.map(k => `${k.kind} ${k.rule} ${k.selector}`), 'stale known entry: it matches nothing, remove it').toEqual([]);
  });
}

test.describe('the gate itself', () => {
  const entry: Known = {view: 'coast', project: 'phone', kind: 'target', rule: 'target-size', selector: 'button.x', reason: 'r', ref: '#12'};
  test('known-list matching is exact, and an entry that matches nothing is stale', () => {
    const hit: Finding = {kind: 'target', rule: 'target-size', selector: 'button.x'};
    expect(compare([hit], [entry], 'coast', 'phone')).toEqual({unexpected: [], stale: []});
    for (const [v, p, f] of [['coast', 'laptop', hit], ['fleet', 'phone', hit], ['coast', 'phone', {...hit, selector: 'button.x.y'}], ['coast', 'phone', {...hit, kind: 'axe'}]] as const)
      expect(compare([f as Finding], [entry], v, p).unexpected).toHaveLength(1);
    expect(compare([], [entry], 'coast', 'phone').stale).toEqual([entry]);
  });
  test('an entry without a reason or with a ref other than #<n> fails', () => {
    expect(knownProblems([entry])).toEqual([]);
    for (const ref of [undefined, '', '12', '#', '#12a', 'https://github.com/x/y/pull/12']) expect(knownProblems([{...entry, ref}])).toHaveLength(1);
    expect(knownProblems([{...entry, reason: ' '}, {...entry, kind: 'contrast'}])).toEqual(['entry 0: bad reason', 'entry 1: bad kind']);
    expect(knownProblems({})).toEqual(['wcag-known.json is not an array']);
  });
  test('inline paragraph links are exempt from 24 px; icon-only buttons and small inputs are not; a hidden skip link is not a target', async ({page}) => {
    await page.setContent(`<style>*{margin:0} .s{width:16px;height:16px;padding:0;border:0} .sr{position:absolute;width:1px;height:1px;overflow:hidden}</style>
      <a class="sr" href="#m">Skip</a><p>See <a href="#a" style="font-size:10px">a</a>.</p><button class="s" aria-label="Close"></button>
      <label class="c"><input type="checkbox" style="width:16px;height:16px"></label><button style="width:30px;height:30px">ok</button><div hidden><button class="s">x</button></div>
      <div id="h"></div><script>document.getElementById('h').attachShadow({mode: 'open'}).innerHTML = '<button class="in" style="width:10px;height:10px"></button>';</script>`);
    expect((await smallTargets(page)).map(f => f.selector)).toEqual(['button.s[aria-label="Close"]', 'label.c > input[type=checkbox]', 'button.in']);
  });
  test('the focus walk ends on a cycle, flags missing rings and hidden stops, and fails a trap with its selector', async ({page}) => {
    await page.setContent(`<style>.sr{position:absolute;width:1px;height:1px;overflow:hidden} .sr:focus{position:static;width:auto;height:auto;outline:2px solid}
      .bare:focus{outline:none}</style><a class="sr" href="#m">Skip</a><button class="ok">a</button><button class="bare">b</button>`);
    expect(await focusWalk(page)).toEqual([{kind: 'focus', rule: 'focus-indicator', selector: 'button.bare'}]);
    await page.setContent(`<input class="t"><button class="n">n</button><script>
      document.querySelector('.t').addEventListener('keydown', e => { if (e.key === 'Tab') e.preventDefault(); });</script>`);
    expect(await focusWalk(page)).toEqual([{kind: 'focus', rule: 'focus-trap', selector: 'input.t'}]);
    // Focus moving inside an open shadow root is not a trap on its host (the History view's CoastMarkup).
    await page.setContent(`<div id="h"></div><button class="z">z</button><script>
      document.getElementById('h').attachShadow({mode: 'open'}).innerHTML = '<button class="a">a</button><button class="b" style="outline:none">b</button>';</script>`);
    expect(await focusWalk(page)).toEqual([{kind: 'focus', rule: 'focus-indicator', selector: 'button.b'}]);
  });
});
