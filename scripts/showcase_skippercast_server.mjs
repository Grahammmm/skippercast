#!/usr/bin/env node
// SkipperCast's server-side freeze for scripts/showcase.py (the `prepare` step in docs/showcase/pages-*.json).
//
//   node scripts/showcase_skippercast_server.mjs <scratch checkout> <ISO time>
//
// The browser's clock is fixed by the capture (page.clock), but pages the Worker renders (ports, species, boats)
// read the Worker's own Date, and the browser-test seed (e2e/seed/*.sql) dates its rows with SQLite's 'now'.
// Both would follow the host's real clock, so the same code could draw different dates on different days. This
// step fixes both to the one ISO time, in the scratch checkout of the revision being captured only:
//   - dist/server/index.js (the built Worker, wrangler.jsonc's `main`) is moved to showcase-app.js, and a new
//     index.js first imports showcase-clock.js, which replaces Date with one whose now() is the fixed time,
//     then re-exports the app; nothing else in the Worker changes;
//   - every 'now' (and CURRENT_TIMESTAMP / CURRENT_DATE) in e2e/seed/*.sql becomes the fixed UTC time.
// Production code and the repository's own files are never touched. Running it twice is harmless (a rebuilt
// index.js is wrapped again; an already wrapped one is left alone). Exits 1, saying why, when the checkout does
// not have the expected layout, so the revision is reported as not rendered rather than captured unfrozen.
import {existsSync, readdirSync, readFileSync, renameSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const MARK = '// showcase: fixed clock wrapper';

export function clockModule(ms) {
  return `${MARK} (scripts/showcase_skippercast_server.mjs)
const FIXED = ${ms};
const Real = globalThis.Date;
// new Date() and Date.now() read the fixed time; new Date(value), Date.parse and Date.UTC are unchanged.
globalThis.Date = new Proxy(Real, {
  construct: (target, args, newTarget) => Reflect.construct(target, args.length ? args : [FIXED], newTarget),
  apply: () => new Real(FIXED).toString(),
  get: (target, key, receiver) => key === 'now' ? () => FIXED : Reflect.get(target, key, receiver),
});
`;
}

export const ENTRY = `${MARK}
import './showcase-clock.js';
export * from './showcase-app.js';
export {default} from './showcase-app.js';
`;

/** The seed SQL with every reading of SQLite's clock replaced by the fixed UTC time ('YYYY-MM-DD HH:MM:SS'). */
export function freezeSql(text, ms) {
  const at = new Date(ms).toISOString().slice(0, 19).replace('T', ' ');
  return text.replace(/'now'/gi, `'${at}'`)
    .replace(/\bCURRENT_TIMESTAMP\b/gi, `'${at}'`)
    .replace(/\bCURRENT_DATE\b/gi, `'${at.slice(0, 10)}'`);
}

export function freeze(tree, iso) {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) throw Error(`not an ISO time: ${iso}`);
  const server = resolve(tree, 'dist/server'), entry = resolve(server, 'index.js');
  if (!existsSync(entry)) throw Error(`${entry} is missing: build the checkout first`);
  if (!readFileSync(entry, 'utf8').startsWith(MARK)) renameSync(entry, resolve(server, 'showcase-app.js'));
  writeFileSync(resolve(server, 'showcase-clock.js'), clockModule(ms));
  writeFileSync(entry, ENTRY);
  const seeds = resolve(tree, 'e2e/seed'), changed = [];
  for (const name of existsSync(seeds) ? readdirSync(seeds).filter(n => n.endsWith('.sql')).sort() : []) {
    const path = resolve(seeds, name), text = readFileSync(path, 'utf8'), frozen = freezeSql(text, ms);
    if (frozen !== text) { writeFileSync(path, frozen); changed.push(name); }
  }
  return {worker: entry, seeds: changed};
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [tree, iso] = process.argv.slice(2);
  try {
    const done = freeze(resolve(tree || '.'), iso);
    console.log(`showcase: Worker clock fixed at ${iso} (${done.worker}); seed files dated: ${done.seeds.join(', ') || 'none'}`);
  } catch (error) {
    console.error(`showcase: cannot fix the server clock: ${error.message}`);
    process.exit(1);
  }
}
