// SC-PERF-JUMP-1 (PERF-BASELINE-1 P10): the app shell does not move while the brief header and the legend fill in.
// Before the fix the laptop /map shifted by 0.8 to 1.6 (CLS): "Loading region…" or the chat entry pushed the masthead onto a second row for a moment,
// the place name gained its coordinates, and the target menu widened and re-wrapped the command bar, moving the whole page down and back.
// The test records every layout-shift entry from the first byte, waits for the parts that used to move (not for a fixed time), and bounds
//   (a) the shifts that touch the masthead or the command bar (they now hold still), and
//   (b) the total, loosely: the brief's own tiles and verdict still change height as live data arrives, and that is not asserted away here.
import {test, expect} from './fixtures.ts';

const SHELL_SHIFT_LIMIT = 0.03;     // masthead + command bar: about 0.012 after the fix (a 4 px nudge), 0.6 to 1.6 before (laptop)
const TOTAL_LIMIT = {phone: 0.1, laptop: 0.3};   // about 0.01 and 0.03 to 0.12 after the fix; 0.01 and 0.85 before

test('the shell and legend reserve their space, so the map page does not jump while it loads', async ({page, v2}, info) => {
  await page.addInitScript(() => {
    const w = window as unknown as {__shifts: {value: number; shell: boolean}[]};
    w.__shifts = [];
    const inShell = (n: Node | null) => !!n && (n.nodeType === 1 ? n as Element : n.parentElement)?.closest('.app-masthead, .app-command') != null;
    new PerformanceObserver(list => {
      for (const e of list.getEntries() as unknown as {value: number; hadRecentInput: boolean; sources?: {node: Node | null}[]}[])
        if (!e.hadRecentInput) w.__shifts.push({value: e.value, shell: (e.sources ?? []).some(s => inShell(s.node))});
    }).observe({type: 'layout-shift', buffered: true});
  });
  await v2.open('app', {region: 'morro-bay'});
  // The parts that used to move have landed: the place name's coordinates, then (laptop) the legend's rules row and the chat entry.
  await expect(page.locator('.app-location-coords').first()).toBeAttached();
  if (info.project.name === 'laptop') {
    await expect(page.locator('.app-legend-mpa')).toBeVisible();
    await expect(page.locator('[data-advisor-entry]')).toBeVisible();
  }
  await page.evaluate(() => document.fonts.ready);
  const shifts = await page.evaluate(() => (window as unknown as {__shifts: {value: number; shell: boolean}[]}).__shifts);
  const total = shifts.reduce((a, s) => a + s.value, 0), shell = shifts.filter(s => s.shell).reduce((a, s) => a + s.value, 0);
  console.log(`${info.project.name}: CLS total ${total.toFixed(4)}, masthead/command bar ${shell.toFixed(4)}, ${shifts.length} shift entries`);
  expect(shell, 'layout shift that touches the masthead or the command bar').toBeLessThanOrEqual(SHELL_SHIFT_LIMIT);
  expect(total, 'total layout shift of the page load').toBeLessThanOrEqual(TOTAL_LIMIT[info.project.name as 'phone' | 'laptop']);
});

test('the legend reserve gives way to a selected-mark card on a short-ish desktop map', async ({page, v2}, info) => {
  test.skip(info.project.name !== 'laptop', 'the reserve applies to the desktop column only');
  await page.setViewportSize({width: 1280, height: 800});
  await v2.open('app', {region: 'morro-bay'});
  await expect(page.locator('.app-legend-mpa')).toBeVisible();
  // Stand in for the selected-mark card: same class and place in the column as the real one.
  await page.locator('.app-chrome-left').evaluate(col => {
    const card = document.createElement('section');
    card.className = 'app-mark';
    card.textContent = 'Selected mark';
    col.insertBefore(card, col.firstChild);
  });
  const box = await page.evaluate(() => {
    const col = document.querySelector('.app-chrome-left')!.getBoundingClientRect();
    const legend = document.querySelector('.app-chrome-left > .app-legend')!.getBoundingClientRect();
    return {column: col.height, legend: legend.height};
  });
  // The 90% reserve would make the legend about 335 px of a 372 px column and push it far below the map's clipped edge; beside a card it keeps only its small minimum.
  expect(box.legend, 'the legend shrinks beside the selected card instead of keeping its loading reserve').toBeLessThan(box.column * 0.4);
});
