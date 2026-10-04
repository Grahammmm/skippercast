#!/usr/bin/env node
// Seeds advisor_rules (docs/plans/text-advisor/02-data-model.md § advisor_rules,
// OP-6) from the reviewed regulation files the app already publishes: every
// jurisdictions/<id>.json names its regulations_asset under dist/, and every
// dist/data/regulations*.json carries its jurisdiction_id. One row per
// jurisdiction and species (region '*': the file covers the whole management
// area), plus the sub-species the rockfish text names (copper, canary,
// vermilion/sunset sub-limits; yelloweye, quillback, cowcod, bronzespotted
// no-retention) and the cabezon/greenling members of the RCG group. A species
// the catalogs do not know becomes species_key 'other' with its label kept.
//
// Every row starts as status 'review' (02: nothing is quotable as current until
// an admin marks it 'active'), reviewed_at = now, review_due = now + 90 days
// (or the season end, when that is sooner and still ahead). Ids are
// deterministic, so running it twice changes nothing; a row whose imported
// content changed goes back to 'review' (a retired row stays retired).
//
//   node scripts/advisor/import-rules.mjs            print the SQL
//   node scripts/advisor/import-rules.mjs --apply    run it on the remote D1 (wrangler)
import {createHash} from 'node:crypto';
import {readFileSync, readdirSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';

export const DATABASE = 'skippercast';
const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const json = path => JSON.parse(readFileSync(join(ROOT, path), 'utf8'));
const DAY = 86400000;
export const REVIEW_DAYS = 90;
export const UPDATED_BY = 'import-rules';

const CATALOG = json('catalog/species.json').species;
const EXTRA = json('catalog/advisor/species-extra.json').species;
/** Every species key the advisor recognises (catalog + species-extra, synonyms canonicalised). */
export const SPECIES_KEYS = new Set([...CATALOG.map(s => s.id), ...EXTRA.filter(e => !e.same_as_parent).map(e => e.key)]);
const SYNONYM = new Map(EXTRA.filter(e => e.same_as_parent).map(e => [e.key, e.parent]));
const NAMES = new Map([...CATALOG.map(s => [s.id, s.name]), ...EXTRA.map(e => [e.key, e.name])]);
// Words the regulation text uses for a species -> the advisor key.
const WORDS = new Map([
  ['copper', 'copper'], ['canary', 'canary'], ['vermilion', 'vermilion'], ['yelloweye', 'yelloweye'], ['cowcod', 'cowcod'],
  ['bronzespotted', 'bronzespotted'], ['bocaccio', 'bocaccio'], ['chilipepper', 'chilipepper'], ['black', 'black'], ['blue', 'blue'],
  ['gopher', 'gopher'], ['cabezon', 'cabezon'], ['greenling', 'kelp-greenling'], ['greenlings', 'kelp-greenling'],
]);

/**
 * The species_key for a regulation file's species id or a word from its text:
 * a catalog or species-extra key (synonyms canonicalised), else 'other'.
 */
export function speciesKeyFor(name) {
  const raw = String(name ?? '').trim().toLowerCase();
  const key = SYNONYM.get(raw) ?? WORDS.get(raw) ?? raw;
  return SPECIES_KEYS.has(key) ? key : 'other';
}

/** The jurisdictions and their regulation files: [{jurisdiction, path, data}]. */
export function regulationFiles(root = ROOT) {
  const read = p => JSON.parse(readFileSync(join(root, p), 'utf8'));
  const out = new Map();
  for (const f of readdirSync(join(root, 'jurisdictions')).filter(f => f.endsWith('.json')).sort()) {
    const j = read(`jurisdictions/${f}`);
    const path = `dist/${j.regulations_asset}`;
    out.set(path, {jurisdiction: j.id, path, data: read(path)});
  }
  // Any dist/data/regulations*.json a jurisdiction file does not point at still gets imported, by its own jurisdiction_id.
  for (const f of readdirSync(join(root, 'dist/data')).filter(f => /^regulations.*\.json$/.test(f)).sort()) {
    const path = `dist/data/${f}`;
    if (!out.has(path)) { const data = read(path); out.set(path, {jurisdiction: data.jurisdiction_id, path, data}); }
  }
  for (const file of out.values()) if (file.data.jurisdiction_id && file.data.jurisdiction_id !== file.jurisdiction)
    throw Error(`${file.path}: jurisdiction_id ${file.data.jurisdiction_id} is not ${file.jurisdiction}`);
  return [...out.values()];
}

const SPECIES_SOURCE = {dungeness: 'rules-crab'};
const FRACTIONS ={'¼': 0.25, '½': 0.5, '¾': 0.75};
/** "22 in minimum total length." -> 22, "5¾ in shell width" -> 5.75; "No minimum" -> null. */
export function sizeInches(text) {
  const m = /^\s*(\d+(?:\.\d+)?)([¼½¾])?\s*in\b/i.exec(String(text ?? ''));
  return m ? Number(m[1]) + (m[2] ? FRACTIONS[m[2]] : 0) : null;
}
/** The daily bag when the text leads with it ("2 per person daily", "When open: 10 per person", "10 total rockfish"); else null. */
export function bagLimit(text) {
  const m = /^\s*(?:when open:\s*)?(\d+)\s+(?:per\b|total\b|combined\b|salmon\b|albacore\b|fish\b|dungeness\b|california\b)/i.exec(String(text ?? ''));
  return m ? Number(m[1]) : null;
}

/** Season bounds from the reviewed windows: one or more -> first start, last end; none -> closed (null, null, closed). */
function season(windows) {
  const list = Array.isArray(windows) ? windows.filter(w => w?.start && w?.end) : [];
  if (!list.length) return {open: null, close: null, closed: true};
  return {open: list[0].start, close: list.at(-1).end, closed: false, notes: list.map(w => w.restriction).filter(Boolean)};
}

const clean = s => String(s ?? '').replace(/\s+/g, ' ').trim();
const join_ = parts => parts.map(clean).filter(Boolean).join(' ') || null;

/** The rule rows (before ids and dates) for one regulation file. */
export function rowsForFile({jurisdiction, data}) {
  const rows = [];
  for (const [id, sp] of Object.entries(data.species ?? {})) {
    // The most specific CDFW page: the species' own (rules-salmon, rules-crab, ...), then the area's, then the first listed.
    const listed = (sp.source_ids ?? []).filter(s => data.sources?.[s]);
    const own = SPECIES_SOURCE[id] ?? `rules-${id}`, area = `rules-${String(jurisdiction).replace(/^california-/, '')}`;
    const sourceId = listed.find(s => s === own) ?? listed.find(s => s === area) ?? listed[0] ?? null;
    const source = sourceId ? data.sources[sourceId] : {name: 'CDFW official regulation index', url: data.official_map_url};
    const s = season(sp.windows);
    const key = speciesKeyFor(id);
    const seasonText = clean(sp.season);
    const base = {
      region: '*', jurisdiction, file_species: id,
      season_open: s.open, season_close: s.close,
      area_notes: join_([s.closed ? `Closed: ${seasonText}` : `Season: ${seasonText}`, ...(s.notes ?? []), data.scope]),
      source_name: clean(source.name), source_url: source.url,
    };
    const details = (sp.details ?? []).map(clean);
    rows.push({...base, species_key: key, species_label: key === 'other' ? clean(sp.name || id) : clean(sp.name || NAMES.get(key) || id),
      size_min_in: sizeInches(sp.size), size_max_in: null, bag_limit: s.closed ? 0 : bagLimit(sp.bag), bag_notes: clean(sp.bag) || null,
      depth_limit_ft: null, gear_notes: join_([clean(sp.size), ...details]) });
    if (id !== 'rockfish') continue;
    // Sub-species the rockfish text names.
    const text = [sp.bag, ...details].join(' ');
    const sub = (word, fields, label) => {
      const k = speciesKeyFor(word);
      const name = k === 'other' ? label : NAMES.get(k);
      if (!rows.some(r => r.species_key === k && r.species_label === name))
        rows.push({...base, species_key: k, species_label: name, size_min_in: null, size_max_in: null, depth_limit_ft: null,
          gear_notes: details.find(d => /hook|descending/i.test(d)) ?? null, ...fields});
    };
    const subLimit = /at most\s+([^.]+?)(?:\s+rockfish)?\s+combined/i.exec(text);
    if (subLimit) for (const m of subLimit[1].matchAll(/(\d+)\s+([a-z]+(?:\/[a-z]+)?)/gi)) {
      const words = m[2].toLowerCase().split('/');
      for (const w of words) sub(w, {bag_limit: Number(m[1]), bag_notes: clean(`Within the rockfish limit: at most ${m[1]} ${m[2]}${words.length > 1 ? ' combined' : ''}. ${clean(sp.bag)}`)},
        `${w[0].toUpperCase()}${w.slice(1)} rockfish`);
    }
    const none = /(?:no retention of|do not retain)\s+([^.]+?)\s+rockfish/i.exec(text);
    if (none) for (const w of none[1].split(/,\s*|\s+or\s+|\s+and\s+/).map(x => x.trim().toLowerCase()).filter(Boolean))
      sub(w, {bag_limit: 0, bag_notes: clean(`No retention. ${none[0]}.`)}, `${w[0].toUpperCase()}${w.slice(1)} rockfish`);
    if (/cabezon/i.test(sp.bag ?? '')) sub('cabezon', {bag_limit: null, bag_notes: clean(`Counts toward: ${clean(sp.bag)}`)}, 'Cabezon');
    if (/greenling/i.test(sp.bag ?? '')) sub('greenling', {bag_limit: null, bag_notes: clean(`Counts toward: ${clean(sp.bag)}`)}, 'Kelp greenling');
  }
  return rows;
}

/** The deterministic row id: (jurisdiction, region, species_key), plus the label for 'other'. */
export const ruleId = row => createHash('sha256').update([row.jurisdiction, row.region, row.species_key, row.species_key === 'other' ? row.species_label : ''].join('|')).digest('hex').slice(0, 32);

const isoDay = ms => new Date(ms).toISOString().slice(0, 10);
/** Every row with its id, status 'review', reviewed_at now and review_due (90 days, or the season end when sooner and not past). */
export function importRows(now = Date.now(), files = regulationFiles()) {
  const today = isoDay(now), due90 = isoDay(now + REVIEW_DAYS * DAY), stamp = new Date(now).toISOString();
  return files.flatMap(rowsForFile).map(row => {
    const end = /^\d{4}-\d{2}-\d{2}$/.test(row.season_close ?? '') && row.season_close >= today && row.season_close < due90 ? row.season_close : due90;
    const {file_species, ...rest} = row;
    return {id: ruleId(row), ...rest, reviewed_at: stamp, review_due: end, status: 'review', updated_by: UPDATED_BY, updated_at: stamp, file_species};
  });
}

export const COLUMNS = ['id', 'region', 'jurisdiction', 'species_key', 'species_label', 'size_min_in', 'size_max_in', 'bag_limit', 'bag_notes',
  'season_open', 'season_close', 'depth_limit_ft', 'area_notes', 'gear_notes', 'source_name', 'source_url', 'reviewed_at', 'review_due',
  'status', 'updated_by', 'updated_at'];
// The imported content: a change in any of these sends the row back to review.
const CONTENT = ['species_label', 'size_min_in', 'size_max_in', 'bag_limit', 'bag_notes', 'season_open', 'season_close', 'depth_limit_ft',
  'area_notes', 'gear_notes', 'source_name', 'source_url'];

const literal = v => v === null || v === undefined ? 'NULL' : typeof v === 'number' ? (Number.isFinite(v) ? String(v) : 'NULL') : `'${String(v).replace(/'/g, "''")}'`;

/** One idempotent statement per row: insert, or update only when the imported content changed. */
export function rulesSql(rows) {
  const set = [...CONTENT.map(c => `${c}=excluded.${c}`), 'reviewed_at=excluded.reviewed_at', 'review_due=excluded.review_due',
    "status=CASE WHEN advisor_rules.status='retired' THEN 'retired' ELSE 'review' END", 'updated_by=excluded.updated_by', 'updated_at=excluded.updated_at'];
  const changed = CONTENT.map(c => `advisor_rules.${c} IS NOT excluded.${c}`).join(' OR ');
  return rows.map(r => `INSERT INTO advisor_rules(${COLUMNS.join(',')}) VALUES(${COLUMNS.map(c => literal(r[c])).join(',')}) ON CONFLICT(id) DO UPDATE SET ${set.join(',')} WHERE ${changed};`).join('\n') + '\n';
}

export const wranglerArgs = file => ['--yes', 'wrangler', 'd1', 'execute', DATABASE, '--remote', '--file', file];

export function main(argv, {run = spawnSync, log = console.log, now = Date.now()} = {}) {
  for (const a of argv) if (a !== '--apply') throw Error(`unknown option ${a}\nusage: node scripts/advisor/import-rules.mjs [--apply]`);
  const sql = rulesSql(importRows(now));
  if (!argv.includes('--apply')) { log(sql.trimEnd()); return 0; }
  const dir = mkdtempSync(join(tmpdir(), 'skippercast-rules-')), file = join(dir, 'advisor-rules.sql');
  try {
    writeFileSync(file, sql);
    const result = run('npx', wranglerArgs(file), {stdio: 'inherit'});
    return result.status ?? 1;
  } finally { rmSync(dir, {recursive: true, force: true}); }
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(e.message); process.exitCode = 2; }
}
