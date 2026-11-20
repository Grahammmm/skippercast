// SC-PERF-JUMP-1 (PERF-BASELINE-1 P10): the app shell does not move while the brief header and the legend fill in.
// Before the fix the laptop /map shifted by 0.8 to 1.6 (CLS): "Loading region…" or the chat entry pushed the masthead onto a second row for a moment,
// the place name gained its coordinates, and the target menu widened and re-wrapped the command bar, moving the whole page down and back.
// The test records eligible layout shifts from navigation, waits for the parts that used to move (not for a fixed time), and bounds
//   (a) the shifts that touch the masthead or the command bar (they now hold still), and
//   (b) the total, loosely: the brief's own tiles and verdict still change height as live data arrives, and that is not asserted away here.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

// Resolves once the legend column and the legend report the same heights on two reads one animation-frame pair apart (a settled layout, not a sleep).
async function settled(page: Page) {
  const read = () => page.evaluate(() => new Promise<string>(done => requestAnimationFrame(() => requestAnimationFrame(() => {
    const h = (sel: string) => document.querySelector(sel)!.getBoundingClientRect().height;
    done(`${h('.app-chrome-left')}/${h('.app-chrome-left > .app-legend')}`);
  }))));
  let last = '';
  await expect.poll(async () => { const now = await read(), same = now === last; last = now; return same; }, {message: 'the legend column stops moving'}).toBe(true);
}

const SHELL_SHIFT_LIMIT = 0.03;     // masthead + command bar: about 0.012 after the fix (a 4 px nudge), 0.6 to 1.6 before (laptop)
const TOTAL_LIMIT = {phone: 0.1, laptop: 0.3};   // about 0.01 and 0.03 to 0.12 after the fix; 0.01 and 0.85 before

type Shift = {startTime: number; value: number; shell: boolean};
type ShiftWindow = Window & {__finishShifts?: () => Shift[]};

function observeShifts() {
  const shifts: Shift[] = [];
  const inShell = (n: Node | null) => !!n && (n.nodeType === 1 ? n as Element : n.parentElement)?.closest('.app-masthead, .app-command') != null;
  const record = (entries: PerformanceEntry[]) => {
    for (const e of entries as (PerformanceEntry & {value: number; hadRecentInput: boolean; sources?: {node: Node | null}[]})[])
      if (!e.hadRecentInput) shifts.push({startTime: e.startTime, value: e.value, shell: (e.sources ?? []).some(s => inShell(s.node))});
  };
  const observer = new PerformanceObserver(list => record(list.getEntries()));
  observer.observe({type: 'layout-shift', buffered: true});
  (window as ShiftWindow).__finishShifts = () => {
    record(observer.takeRecords());
    observer.disconnect();
    return shifts;
  };
}

async function finishShifts() {
  await document.fonts.ready;
  // rAF runs before paint; the second frame lets the final relevant layout be recorded.
  await new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done())));
  return (window as ShiftWindow).__finishShifts!();
}

function summarizeShifts(shifts: Shift[]) {
  let cls = 0, total = 0, shell = 0, score = 0, first = -Infinity, previous = -Infinity;
  for (const {startTime, value, shell: touchesShell} of shifts.sort((a, b) => a.startTime - b.startTime)) {
    // A CLS session has gaps strictly below 1s and lasts strictly less than 5s.
    if (startTime - previous >= 1000 || startTime - first >= 5000) {
      score = 0;
      first = startTime;
    }
    previous = startTime;
    score += value;
    cls = Math.max(cls, score);
    total += value;
    if (touchesShell) shell += value;
  }
  return {cls, total, shell};
}

test('load CLS uses the largest session, not the total shift', () => {
  // Binary fractions keep the summation exact. A lifetime sum or a per-entry max both fail.
  const burst = [0, 500].map(startTime => ({startTime, value: 0.0625, shell: true}));
  expect(summarizeShifts(burst)).toEqual({cls: 0.125, total: 0.125, shell: 0.125});
  expect(summarizeShifts([...burst, {startTime: 1500, value: 0.09375, shell: false}]))
    .toEqual({cls: 0.125, total: 0.21875, shell: 0.125});
  // Each gap is under 1s, but the final entry is exactly 5s from the start.
  const longBurst = [0, 800, 1600, 2400, 3200, 4000, 4800, 5000]
    .map(startTime => ({startTime, value: 0.0625, shell: false}));
  expect(summarizeShifts(longBurst)).toEqual({cls: 0.4375, total: 0.5, shell: 0});
});

test('the shell and legend reserve their space, so the map page does not jump while it loads', async ({page, v2}, info) => {
  await page.addInitScript(observeShifts);
  await v2.open('app', {region: 'morro-bay'});
  // The parts that used to move have landed: the place name's coordinates, then (laptop) the legend's rules row and the chat entry.
  await expect(page.locator('.app-location-coords').first()).toBeAttached();
  if (info.project.name === 'laptop') {
    await expect(page.locator('.app-legend-mpa')).toBeVisible();
    await expect(page.locator('[data-advisor-entry]')).toBeVisible();
  }
  const shifts = await page.evaluate(finishShifts);
  const {cls, total, shell} = summarizeShifts(shifts);
  console.log(`${info.project.name}: load CLS ${cls.toFixed(4)}, total layout shift ${total.toFixed(4)}, masthead/command bar ${shell.toFixed(4)}, ${shifts.length} shift entries`);
  expect(shell, 'layout shift that touches the masthead or the command bar').toBeLessThanOrEqual(SHELL_SHIFT_LIMIT);
  expect(total, 'total layout shift of the page load').toBeLessThanOrEqual(TOTAL_LIMIT[info.project.name as 'phone' | 'laptop']);
});

test('the legend reserve gives way to a selected-mark card on a short-ish desktop map', async ({page, v2}, info) => {
  test.skip(info.project.name !== 'laptop', 'the reserve applies to the desktop column only');
  await page.setViewportSize({width: 1280, height: 800});
  await v2.open('app', {region: 'morro-bay'});
  await expect(page.locator('.app-legend-mpa')).toBeVisible();
  // The MPA key appears before the source guard reveals the answer above this short map.
  await expect(page.locator('.app-first-answer')).toBeVisible();
  await settled(page);   // the 90% loading reserve has settled before the card arrives
  // Stand in for the selected-mark card: same class and place in the column as the real one.
  await page.locator('.app-chrome-left').evaluate(col => {
    const card = document.createElement('section');
    card.className = 'app-mark';
    card.textContent = 'Selected mark';
    col.insertBefore(card, col.firstChild);
  });
  await settled(page);   // the legend has given way beside the card
  const box = await page.evaluate(() => {
    const col = document.querySelector('.app-chrome-left')!.getBoundingClientRect();
    const legend = document.querySelector('.app-chrome-left > .app-legend')!.getBoundingClientRect();
    return {column: col.height, legend: legend.height};
  });
  // The 90% reserve would make the legend about 335 px of a 372 px column and push it far below the map's clipped edge; beside a card it keeps only its small minimum.
  expect(box.legend, 'the legend shrinks beside the selected card instead of keeping its loading reserve').toBeLessThan(box.column * 0.4);
});
