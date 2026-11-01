// scripts/showcase_capture.mjs, the before/after gallery's browser driver (SHOWCASE-1): run for real against a
// throwaway local HTTP server, so a crashed or erroring page can never be shown as a "new page" or as evidence of
// "no visible change". Only HTTP 404/410 means the route is absent; a server error, an uncaught page error, a
// blank page or a readiness selector that never appears is a failed capture with no screenshot.
// Runs once (phone project); it starts its own browser through the driver and never touches the app server.
import {spawn, spawnSync} from 'node:child_process';
import {createServer} from 'node:http';
import {existsSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {test, expect} from '@playwright/test';

const PAGES: Record<string, [number, string]> = {
  '/ok': [200, '<!doctype html><title>ok</title><h1>Ready</h1><p>A page that rendered.</p>'],
  '/gone': [404, '<!doctype html><title>not found</title><h1>Not found</h1>'],
  '/broken': [500, '<!doctype html><title>error</title><h1>Internal error</h1>'],
  '/crash': [200, '<!doctype html><title>app</title><div id="app"></div><script>throw new Error("render boot failure")</script>'],
  '/crash-shell': [200, '<!doctype html><title>app</title><h1>Shell</h1><script>throw new Error("late failure")</script>'],
  '/blank': [200, '<!doctype html><title>app</title><div id="app"></div>'],
  '/unready': [200, '<!doctype html><title>app</title><p>Loading…</p>'],
};

test('the capture driver tells a missing route from a failed render', async ({}, info) => {
  test.skip(info.project.name !== 'phone', 'one browser run is enough; the driver sets its own viewport');
  test.setTimeout(120_000);
  const server = createServer((request, response) => {
    const [status, body] = PAGES[new URL(request.url ?? '/', 'http://x').pathname] ?? [404, 'not found'];
    response.writeHead(status, {'content-type': 'text/html; charset=utf-8'}).end(body);
  });
  await new Promise<void>(done => server.listen(0, '127.0.0.1', done));
  try {
    const {port} = server.address() as {port: number};
    const out = info.outputPath('capture');
    const job = info.outputPath('job.json');
    const page = (id: string, extra = {}) => ({id, path: `/${id}`, viewport: 'phone', settle_ms: 0, max_settle_ms: 3000, ...extra});
    writeFileSync(job, JSON.stringify({base_url: `http://127.0.0.1:${port}`, out_dir: out, root: '.', now: '2026-10-31T19:00:00Z', seed: 1,
      pages: [page('ok', {ready: 'h1'}), page('gone'), page('broken'), page('crash'), page('crash-shell', {ready: 'h1'}), page('blank'),
        page('unready', {ready: '#app'})]}));
    // Asynchronous: the server above answers from this process's event loop while the driver runs.
    const run = await new Promise<{status: number | null; output: string}>(done => {
      const child = spawn(process.execPath, [resolve('scripts/showcase_capture.mjs'), job], {stdio: ['ignore', 'pipe', 'pipe']});
      let output = '';
      child.stdout.on('data', chunk => { output += chunk; });
      child.stderr.on('data', chunk => { output += chunk; });
      child.on('close', status => done({status, output}));
    });
    expect(run.status, run.output).toBe(0);
    const rows = Object.fromEntries(JSON.parse(readFileSync(join(out, 'results.json'), 'utf8')).map((r: {id: string}) => [r.id, r]));
    expect(rows.ok).toMatchObject({status: 'ok', http_status: 200, steady: true, page_errors: []});
    expect(rows.gone).toMatchObject({status: 'missing', http_status: 404});
    expect(rows.broken).toMatchObject({status: 'failed', http_status: 500, error: 'HTTP 500'});
    expect(rows.crash).toMatchObject({status: 'failed', http_status: 200, error: 'the page threw: Error: render boot failure'});
    // Text on screen does not save a page that threw: its picture may be half drawn.
    expect(rows['crash-shell']).toMatchObject({status: 'failed', http_status: 200, error: 'the page threw: Error: late failure'});
    expect(rows.blank).toMatchObject({status: 'failed', error: 'blank page: no text or image was drawn'});
    expect(rows.unready).toMatchObject({status: 'failed', error: 'Error: not rendered: #app never appeared'});
    // Only a page that rendered has a screenshot to show.
    for (const id of Object.keys(PAGES)) expect(existsSync(join(out, `${id.slice(1)}.png`)), id).toBe(id === '/ok');
  } finally {
    server.close();
  }
});

// Compare mode: rendering noise between two independent captures of one revision is not a change, while the
// smallest real changes still are. The noise pair is real: tests/fixtures/showcase/cambria-c69a97e48-capture-*.png
// are the Cambria Chart at commit c69a97e48 from two independent builds and captures (the first gallery run and
// the reviewer's rerun), which differ in 50 pixels, all on anti-aliased edges or within a few colour levels.
test('the comparison ignores rendering noise and still counts a one-letter change', async ({page}, info) => {
  test.skip(info.project.name !== 'phone', 'one browser run is enough; the driver decodes the PNGs itself');
  test.setTimeout(120_000);
  const shot = async (body: string, name: string) => {
    await page.setViewportSize({width: 240, height: 80});
    await page.setContent(`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><body style="margin:0;background:#0b1a26;color:#e8f1f5;font:16px/1.4 sans-serif">${body}</body>`);
    const file = info.outputPath(`${name}.png`);
    writeFileSync(file, await page.screenshot());
    return file;
  };
  const button = (colour: string) => `<p style="margin:12px">Wind</p><span style="display:inline-block;margin:0 12px;padding:6px 14px;background:${colour}">Go</span>`;
  const files = {
    text: await shot('<p style="margin:12px">Wind 12 kn, gusts 18</p>', 'text'),
    textAgain: await shot('<p style="margin:12px">Wind 12 kn, gusts 18</p>', 'text-again'),
    letter: await shot('<p style="margin:12px">Wind 13 kn, gusts 18</p>', 'letter'),
    line: await shot('<div style="margin:20px;height:1px;background:#4fd1c5"></div>', 'line'),
    lineMoved: await shot('<div style="margin:21px 20px;height:1px;background:#4fd1c5"></div>', 'line-moved'),
    colour: await shot(button('#1e88e5'), 'colour'),
    colourTweaked: await shot(button('#1976d2'), 'colour-tweaked'),
  };
  const out = info.outputPath('compare.json'), job = info.outputPath('compare-job.json');
  const pair = (id: string, before: string, after: string) => ({id, before, after});
  writeFileSync(job, JSON.stringify({out, tolerance: 8, compare: [
    pair('noise', 'tests/fixtures/showcase/cambria-c69a97e48-capture-1.png', 'tests/fixtures/showcase/cambria-c69a97e48-capture-2.png'),
    pair('same', files.text, files.textAgain), pair('letter', files.text, files.letter),
    pair('line', files.line, files.lineMoved), pair('colour', files.colour, files.colourTweaked)]}));
  const run = spawnSync(process.execPath, [resolve('scripts/showcase_capture.mjs'), job], {encoding: 'utf8'});
  expect(run.status, run.stderr).toBe(0);
  const rows = Object.fromEntries(JSON.parse(readFileSync(out, 'utf8')).map((r: {id: string}) => [r.id, r]));
  // The same commit twice: pixels differ, but none counts as a change.
  expect(rows.noise).toMatchObject({changed: 0, exact: 50});
  expect(rows.same).toMatchObject({changed: 0, exact: 0});
  // One digit, a one-pixel move and a darker button are real changes.
  for (const id of ['letter', 'line', 'colour']) expect(rows[id].changed, id).toBeGreaterThan(10);
});
