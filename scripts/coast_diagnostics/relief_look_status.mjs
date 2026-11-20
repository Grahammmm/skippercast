// Offline pointer diagnostic; this does not verify or fetch the referenced tiles.
import {readFileSync} from 'node:fs';
import {parseArgs} from 'node:util';
import {lookDepthKey} from '../../web/map/legend-model.ts';
import {LEGACY_LOOK, resolveRelief} from '../../web/map/relief-data.ts';

const USAGE = 'Usage: node scripts/coast_diagnostics/relief_look_status.mjs <pointer.json>... [--json]';
const LABELS = {
  refused: 'refused',
  legacy: 'legacy look',
  known: 'known look',
  unknown: 'unknown/malformed look',
};

function inspectPointer(path) {
  let source;
  try {
    source = readFileSync(path, 'utf8');
  } catch {
    return {path, status: 'refused', reason: 'unreadable-file'};
  }
  let pointer;
  try {
    pointer = JSON.parse(source);
  } catch {
    return {path, status: 'refused', reason: 'invalid-json'};
  }

  // Paths may be staging filenames; inspect the region declared in the pointer.
  const region = typeof pointer?.region === 'string' ? pointer.region : null;
  const result = resolveRelief(region ?? '', pointer);
  if (result.status !== 'ready') return {path, region, status: 'refused', reason: result.reason};

  // Use the resolved current look and the Chart's default lookup, not previous.style.
  const {look} = result.archive;
  const recognised = lookDepthKey(look, 'dark').status === 'chips';
  const status = !recognised ? 'unknown' : look === LEGACY_LOOK ? 'legacy' : 'known';
  return {path, region, status, look};
}

function main(args) {
  let parsed;
  try {
    parsed = parseArgs({args, options: {json: {type: 'boolean'}}, allowPositionals: true});
    if (!parsed.positionals.length) throw new Error('Supply at least one pointer file.');
  } catch (error) {
    console.error(`${error.message}\n${USAGE}`);
    return 2;
  }

  const rows = parsed.positionals.map(inspectPointer);
  if (parsed.values.json) console.log(JSON.stringify(rows, null, 2));
  else for (const {path, region, status, look, reason} of rows) {
    const detail = look ?? reason;
    console.log(`${path}${region ? ` [${region}]` : ''}: ${LABELS[status]}${detail ? ` (${detail})` : ''}`);
  }
  // A completed report is not a publication gate, regardless of its verdicts.
  return 0;
}

process.exitCode = main(process.argv.slice(2));
