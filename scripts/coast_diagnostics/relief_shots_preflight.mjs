#!/usr/bin/env node
import {accessSync, constants, statSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const note = 'Present means found on disk, not that Chromium launches or screenshots work.';

function check(kind, name, locate, mode = constants.R_OK) {
  let path = null;
  try {
    path = locate();
    if (!path) throw new Error('no path for this platform');
    if (!statSync(path).isFile()) throw new Error('not a regular file');
    accessSync(path, mode);
    return {kind, name, present: true, path};
  } catch (error) {
    return {kind, name, present: false, path, reason: error.code ?? error.message};
  }
}

// This sibling script and qa_shots.mjs resolve from the same checkout, not cwd.
const resolveFile = name => () => fileURLToPath(import.meta.resolve(name));

function headlessChromium(playwrightTest) {
  if (!playwrightTest.present) throw new Error('cannot resolve without @playwright/test');
  // Follow the installed dependency chain (including pnpm's nested links).
  const playwright = createRequire(playwrightTest.path).resolve('playwright');
  // Chromium.executablePath() points at full Chromium, but the default
  // headless launch in qa_shots.mjs selects the pinned headless shell.
  // Use that Playwright version's registry for platform, revision and cache path.
  const {registry: {registry}} = createRequire(playwright)('playwright-core/lib/coreBundle');
  return registry.findExecutable('chromium-headless-shell')?.executablePath();
}

const args = process.argv.slice(2);
if (args.length > 1 || (args.length === 1 && args[0] !== '--json')) {
  console.error('Usage: node scripts/coast_diagnostics/relief_shots_preflight.mjs [--json]');
  process.exitCode = 2;
} else {
  const playwright = check('module', '@playwright/test', resolveFile('@playwright/test'));
  const worker = 'maplibre-gl/dist/maplibre-gl-worker.mjs';
  const checks = [
    playwright,
    check('module', 'esbuild', resolveFile('esbuild')),
    check('worker', worker, resolveFile(worker)),
    check('executable', 'Chromium (chromium-headless-shell)', () => headlessChromium(playwright), constants.X_OK),
  ];
  const ok = checks.every(item => item.present);
  if (args[0] === '--json') {
    console.log(JSON.stringify({ok, checks, note}, null, 2));
  } else {
    for (const {kind, name, present, path, reason} of checks) {
      console.log(`${present ? 'present' : 'missing'} ${kind}: ${name}${path ? ` — ${path}` : ''}${reason ? ` (${reason})` : ''}`);
    }
    console.log(note);
  }
  process.exitCode = ok ? 0 : 1;
}
