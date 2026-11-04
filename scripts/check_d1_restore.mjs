// Offline coverage check for the owner-only D1 restore runbook (SC0022-02).
//
// Every table that db/schema.ts defines must appear exactly once, by name, in each of
// three marked sections of docs/operations/runbooks/d1-restore.md: the inventory table,
// the row-count query and the clear (drop) list. Wrangler's own `d1_migrations` is the
// one extra name. A name in prose, in a comment or in another block never counts.
//
// This is a bounded checker for a documented format, not a general TypeScript or SQL
// parser. It only reads two text files: it never runs SQL, starts Wrangler, imports the
// runtime schema or reaches the network, and it prints no data rows.
//
//   node scripts/check_d1_restore.mjs [--root PATH]
//   exit 0 complete coverage | 1 unreadable input or coverage failure | 2 bad flags
import {readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

export const SCHEMA_PATH = 'db/schema.ts';
export const RUNBOOK_PATH = 'docs/operations/runbooks/d1-restore.md';
export const BOOKKEEPING_TABLE = 'd1_migrations';
export const SUCCESS_MESSAGE = 'D1 restore runbook coverage passed.';
export const PREFIX = `${RUNBOOK_PATH}: D1 restore coverage: `;
export const SECTIONS = ['inventory', 'counts', 'clear'];
export const INVENTORY_HEADER = ['Table', 'Contents / sensitivity', 'Retention / deletion in current code', 'Source'];
export const marker = (section, edge) => `<!-- d1-restore:${section}:${edge} -->`;

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const list = names => [...new Set(names)].sort().join(', ');

/** Blank out comments, keeping string literals and line structure, so offsets stay stable. */
function stripComments(source) {
  let out = '', i = 0;
  while (i < source.length) {
    const c = source[i], d = source[i + 1];
    if (c === '/' && d === '/') { while (i < source.length && source[i] !== '\n') i++; continue; }
    if (c === '/' && d === '*') {
      const end = source.indexOf('*/', i + 2);
      const stop = end < 0 ? source.length : end + 2;
      out += source.slice(i, stop).replace(/[^\n]/g, ' ');
      i = stop; continue;
    }
    if (c === "'" || c === '"' || c === '`') {
      let j = i + 1;
      while (j < source.length && source[j] !== c) j += source[j] === '\\' ? 2 : 1;
      out += source.slice(i, j + 1); i = j + 1; continue;
    }
    out += c; i++;
  }
  return out;
}

/** The literal table names of every `sqliteTable(...)` call, or the reasons it cannot tell. */
export function parseSchemaTables(schema) {
  const errors = [];
  if (typeof schema !== 'string') return {tables: [], errors: ['schema is not text']};
  // The import statement names sqliteTable without calling it.
  const code = stripComments(schema).replace(/^\s*import\s[^;]*?from\s*(['"])[^'"]*\1\s*;?/gm, match => match.replace(/[^\n]/g, ' '));
  const tables = [];
  for (const m of code.matchAll(/\bsqliteTable\w*/g)) {
    const rest = code.slice(m.index + m[0].length);
    const call = m[0] === 'sqliteTable' ? /^\s*\(\s*(?:'([^'\\\n]*)'|"([^"\\\n]*)")\s*,/.exec(rest) : null;
    const name = call ? (call[1] ?? call[2]) : null;
    if (name === null || !NAME.test(name)) {
      const line = code.slice(0, m.index).split('\n').length;
      errors.push(`unsupported or ambiguous table declaration at line ${line} (${m[0]}); use sqliteTable('literal_name', ...)`);
    } else tables.push(name);
  }
  if (!errors.length && !tables.length) errors.push('no sqliteTable declarations found');
  const seen = new Set(), repeated = new Set();
  for (const t of tables) (seen.has(t) ? repeated : seen).add(t);
  if (repeated.size) errors.push(`table declared more than once: ${list(repeated)}`);
  return {tables, errors};
}

/** The text strictly between one start marker and one end marker, or why not. */
function section(runbook, name) {
  const start = marker(name, 'start'), end = marker(name, 'end');
  const starts = runbook.split(start).length - 1, ends = runbook.split(end).length - 1;
  if (starts !== 1 || ends !== 1) return {error: `malformed block: expected exactly one start and one end marker, found ${starts} and ${ends}`};
  const from = runbook.indexOf(start) + start.length, to = runbook.indexOf(end);
  if (to < from) return {error: 'malformed block: end marker comes before start marker'};
  const body = runbook.slice(from, to);
  if (!body.trim()) return {error: 'malformed block: empty'};
  return {body};
}

/** The body of the single ```sql fence of a block, or why not. */
function fenced(body) {
  const lines = body.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 3 || lines[0] !== '```sql' || lines.at(-1) !== '```' || lines.slice(1, -1).some(l => l.startsWith('```'))) {
    return {error: 'malformed block: expected one ```sql fence and nothing else'};
  }
  return {lines: lines.slice(1, -1)};
}

function inventoryNames(body) {
  const rows = body.split('\n').map(l => l.trim()).filter(Boolean);
  const cells = line => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
  if (!rows.every(r => r.startsWith('|') && r.endsWith('|'))) return {error: 'malformed block: only table rows are allowed'};
  if (rows.length < 3) return {error: 'malformed block: header, separator and rows expected'};
  if (cells(rows[0]).join('|') !== INVENTORY_HEADER.join('|')) return {error: `malformed block: header must be | ${INVENTORY_HEADER.join(' | ')} |`};
  if (!/^\|(?:\s*:?-{3,}:?\s*\|){4}$/.test(rows[1])) return {error: 'malformed block: separator row expected after the header'};
  const names = [];
  for (const [index, row] of rows.slice(2).entries()) {
    const c = cells(row);
    const named = c.length === 4 ? /^`([a-z_][a-z0-9_]*)`$/.exec(c[0]) : null;
    if (!named) return {error: `malformed block: row ${index + 1} needs four cells and one backticked table name first`};
    if (c.slice(1).some(x => !x)) return {error: `malformed block: row for ${named[1]} has an empty cell`};
    names.push(named[1]);
  }
  return {names};
}

function countNames(body) {
  const fence = fenced(body);
  if (fence.error) return fence;
  const sql = fence.lines.join(' ').replace(/\s+/g, ' ').trim();
  if (!sql.endsWith(';') || sql.slice(0, -1).includes(';')) return {error: 'malformed block: one statement terminated by a single ;'};
  const names = [], mismatched = [];
  for (const part of sql.slice(0, -1).split(/\s+UNION ALL\s+/)) {
    const m = /^SELECT '([a-z_][a-z0-9_]*)' AS table_name, COUNT\(\*\) AS row_count FROM ([a-z_][a-z0-9_]*)$/.exec(part.trim());
    if (!m) return {error: `malformed block: unexpected SQL: ${part.trim().slice(0, 60)}`};
    if (m[1] !== m[2]) mismatched.push(`${m[1]} labelled for ${m[2]}`);
    names.push(m[2]);
  }
  if (mismatched.length) return {error: `malformed block: label differs from FROM table: ${mismatched.sort().join('; ')}`};
  return {names};
}

function clearNames(body) {
  const fence = fenced(body);
  if (fence.error) return fence;
  const names = [];
  for (const line of fence.lines) {
    const m = /^DROP TABLE IF EXISTS ([a-z_][a-z0-9_]*);$/.exec(line);
    if (!m) return {error: `malformed block: unexpected SQL: ${line.slice(0, 60)}`};
    if (/^(sqlite_|_cf_)/.test(m[1])) return {error: `malformed block: internal table ${m[1]} must not be dropped`};
    names.push(m[1]);
  }
  return {names};
}

const PARSERS = {inventory: inventoryNames, counts: countNames, clear: clearNames};

/**
 * @param {{schema: string, runbook: string}} input file texts
 * @returns {string[]} deterministic diagnostics, empty when coverage is complete
 */
export function checkD1Restore({schema, runbook}) {
  const out = [];
  const add = (where, message) => out.push(`${PREFIX}${where}: ${message}`);
  const parsed = parseSchemaTables(schema);
  for (const e of parsed.errors) add('schema', e);
  if (typeof runbook !== 'string') { add('runbook', 'runbook is not text'); return out; }
  const wanted = new Set([...parsed.tables, BOOKKEEPING_TABLE]);
  for (const name of SECTIONS) {
    const found = section(runbook, name);
    const result = found.error ? found : PARSERS[name](found.body);
    if (result.error) { add(name, result.error); continue; }
    if (parsed.errors.length) continue;
    const count = new Map();
    for (const n of result.names) count.set(n, (count.get(n) ?? 0) + 1);
    const missing = [...wanted].filter(n => !count.has(n)), extra = [...count.keys()].filter(n => !wanted.has(n));
    const duplicate = [...count].filter(([, c]) => c > 1).map(([n]) => n);
    if (missing.length) add(name, `missing ${list(missing)}`);
    if (extra.length) add(name, `extra ${list(extra)}`);
    if (duplicate.length) add(name, `duplicate ${list(duplicate)}`);
  }
  return out;
}

/** Parse argv (after the script): only `--root PATH`. */
export function parseArgs(args) {
  let root = null;
  for (let i = 0; i < args.length; i++) {
    if (args[i] !== '--root' || root !== null) return {error: `unknown or repeated flag: ${args[i]}`};
    const value = args[++i];
    if (value === undefined || value === '' || value.startsWith('--')) return {error: '--root needs a path'};
    root = value;
  }
  return {root};
}

export function main(args, io = {out: s => console.log(s), err: s => console.error(s)}) {
  const parsed = parseArgs(args);
  if (parsed.error) { io.err(`${parsed.error}\nusage: node scripts/check_d1_restore.mjs [--root PATH]`); return 2; }
  const root = parsed.root ? resolve(parsed.root) : fileURLToPath(new URL('../', import.meta.url));
  let schema, runbook;
  try {
    schema = readFileSync(join(root, SCHEMA_PATH), 'utf8');
    runbook = readFileSync(join(root, RUNBOOK_PATH), 'utf8');
  } catch (e) {
    io.err(`${PREFIX}cannot read input: ${e.code || e.message}`);
    return 1;
  }
  const problems = checkD1Restore({schema, runbook});
  if (problems.length) { for (const p of problems) io.err(p); return 1; }
  io.out(SUCCESS_MESSAGE);
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = main(process.argv.slice(2));
