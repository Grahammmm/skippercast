// SC0022-02: the owner-only D1 restore runbook names every table db/schema.ts defines, in its
// inventory, its count query and its clear list, and a repository check fails when one is missing.
// All data here is synthetic and in memory (node:sqlite); nothing touches D1, Wrangler or the network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {PREFIX, RUNBOOK_PATH, SCHEMA_PATH, SUCCESS_MESSAGE, checkD1Restore, marker, parseSchemaTables} from '../scripts/check_d1_restore.mjs';
import {advisorDatabase, journal, sqliteUnavailable} from './_advisor_d1.mjs';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const SCRIPT = join(ROOT, 'scripts/check_d1_restore.mjs');
const read = path => readFileSync(join(ROOT, path), 'utf8');
const SCHEMA = read(SCHEMA_PATH), RUNBOOK = read(RUNBOOK_PATH);
const schemaTables = () => parseSchemaTables(SCHEMA).tables;
const diag = (section, message) => `${PREFIX}${section}: ${message}`;
const check = (runbook, schema = SCHEMA) => checkD1Restore({schema, runbook});

// ---- text helpers over the marked blocks ----------------------------------------------------
const edge = (section, which) => marker(section, which);
const body = (runbook, section) => runbook.split(edge(section, 'start'))[1].split(edge(section, 'end'))[0];
const withBody = (runbook, section, fn) => {
  const text = body(runbook, section);
  return runbook.replace(edge(section, 'start') + text + edge(section, 'end'), edge(section, 'start') + fn(text) + edge(section, 'end'));
};
const sqlOf = (runbook, section) => body(runbook, section).split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('```')).join('\n');
const row = name => `| \`${name}\` | synthetic | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement | test |\n`;
const select = name => `SELECT '${name}' AS table_name, COUNT(*) AS row_count FROM ${name}`;
const without = (section, name) => runbook => withBody(runbook, section, text => text.split('\n').filter(l =>
  section === 'inventory' ? !l.startsWith(`| \`${name}\` |`) : section === 'counts' ? !l.includes(`SELECT '${name}' AS`) : l.trim() !== `DROP TABLE IF EXISTS ${name};`).join('\n'));
const adding = (section, name) => runbook => withBody(runbook, section, text =>
  section === 'inventory' ? text.replace(/\n$/, '\n') + row(name) : section === 'counts' ? text.replace(/;\n```/, `\nUNION ALL ${select(name)};\n\`\`\``)
    : text.replace(/\n```\s*$/, `\nDROP TABLE IF EXISTS ${name};\n\`\`\`\n`));
const PROBE = "\nexport const probe=sqliteTable('synthetic_restore_probe',{id:text('id').primaryKey()});\n";

// ---- runbook_covers_every_schema_table -----------------------------------------------------
test('runbook_covers_every_schema_table', () => {
  assert.deepEqual(check(RUNBOOK), []);
  const tables = schemaTables();
  assert.ok(tables.length > 6 && new Set(tables).size === tables.length, 'schema parsed to a unique table list');
  for (const section of ['inventory', 'counts', 'clear']) {
    const named = section === 'inventory' ? [...body(RUNBOOK, section).matchAll(/^\| `([a-z_0-9]+)` \|/gm)].map(m => m[1])
      : section === 'counts' ? [...sqlOf(RUNBOOK, section).matchAll(/FROM ([a-z_0-9]+)/g)].map(m => m[1])
        : [...sqlOf(RUNBOOK, section).matchAll(/EXISTS ([a-z_0-9]+);/g)].map(m => m[1]);
    assert.ok(util_equal([...named].sort(), [...tables, 'd1_migrations'].sort()), `${section} names every schema table plus d1_migrations exactly once`);
  }
  // Owner-only rule and the explicit stop wording remain.
  assert.match(RUNBOOK, /\*\*Owner:\*\* repository owner\. Restores overwrite user data and must be done by the owner, never by an agent\./);
  assert.ok(RUNBOOK.includes('**STOP: schema or counts do not match the reviewed restore; do not clear production.**'));
  assert.match(RUNBOOK, /Time Travel/);
  assert.match(RUNBOOK, /Privacy after any restore/);
  assert.doesNotMatch(RUNBOOK, /rate-limit rows only/);
  // The old inline DROP command is gone: the clear step runs the marked block from a file.
  assert.doesNotMatch(RUNBOOK, /--command "DROP TABLE/);
  assert.match(RUNBOOK, /--file restore-clear\.sql/);
  assert.match(RUNBOOK, /--file restore-counts\.sql/);

  // Retention as the code does it: each family keeps its own rule.
  const rule = name => RUNBOOK.split('\n').find(l => l.startsWith(`| \`${name}\` |`));
  const none = 'No automatic age-based deletion found in current code';
  assert.match(rule('trips'), /90 days/);
  assert.match(rule('alert_events'), /90 days/);
  assert.match(rule('delivery_receipts'), /no age test of its own/);
  assert.match(rule('comfort_feedback'), /365 days/);
  assert.match(rule('advisor_messages'), /180 days[^|]*row stays/);
  assert.match(rule('advisor_media'), /90 days[^|]*row stays/);
  assert.match(rule('advisor_reviews'), /90 days after `decided_at`/);
  assert.match(rule('advisor_daily_answers'), /30 days/);
  assert.match(rule('advisor_post_stats'), /730 days/);
  assert.match(rule('job_state'), /No whole-table age limit/);
  // Outreach: the vessel removal request erases the operator's rows (audit notes too) in the removal batch; current consent stays; no age rule.
  assert.match(rule('fleet_outreach'), /`editVessel` with `removal_requested`/);
  assert.match(rule('fleet_outreach'), /same D1 batch as the removal date/);
  assert.match(rule('fleet_outreach'), /including consent-change and status audit notes/);
  assert.match(rule('fleet_outreach'), /current consent stays on `fleet_operators`/);
  assert.match(rule('fleet_outreach'), /operator-wide even when the operator has other listed vessels/);
  assert.ok(rule('fleet_outreach').includes(none), 'fleet_outreach has no age rule');
  assert.doesNotMatch(rule('fleet_outreach'), /no `DELETE` for the table exists/, 'the obsolete no-delete caveat is gone');
  for (const name of ['catch_log', 'saved_spots', 'users', 'passkeys', 'advisor_rules', 'advisor_posts', 'advisor_crew', 'advisor_reports', 'advisor_report_edits']) {
    assert.ok(rule(name).includes(none), `${name} has no age rule`);
    assert.doesNotMatch(rule(name), /\b(90|365|180|30|730) days/, `${name} does not inherit another table's limit`);
  }
  for (const name of tables.filter(t => t.startsWith('fleet_'))) assert.doesNotMatch(rule(name), /\b(90|365|180|30|730) days/, `${name} has no invented TTL`);

  // Clear order: dependents before parents, d1_migrations last, families in the documented sequence.
  const drops = [...sqlOf(RUNBOOK, 'clear').matchAll(/EXISTS ([a-z_0-9]+);/g)].map(m => m[1]);
  const at = n => drops.indexOf(n);
  const before = [['advisor_post_stats', 'advisor_posts'], ['advisor_report_edits', 'advisor_reports'], ['advisor_reviews', 'advisor_reports'], ['advisor_reports', 'advisor_boats'],
    ['advisor_crew', 'advisor_boats'], ['advisor_media', 'advisor_boats'], ['advisor_messages', 'advisor_contacts'], ['advisor_boats', 'advisor_contacts'],
    ['fleet_trip_reports', 'fleet_trips'], ['fleet_segment_labels', 'fleet_trips'], ['fleet_events', 'fleet_segments'], ['fleet_segments', 'fleet_trips'], ['fleet_departures', 'fleet_offerings'],
    ['fleet_offerings', 'fleet_vessels'], ['fleet_vessel_facts', 'fleet_vessels'], ['fleet_aliases', 'fleet_vessels'], ['fleet_ais_watch', 'fleet_vessels'], ['fleet_link_clicks', 'fleet_vessels'],
    ['fleet_changes', 'fleet_vessels'], ['fleet_outreach', 'fleet_operators'], ['advisor_contacts', 'fleet_trip_reports'], ['fleet_operators', 'delivery_receipts'],
    ['delivery_receipts', 'alert_events'], ['alert_events', 'trips'], ['subscriptions', 'users'], ['trips', 'users'], ['catch_log', 'users'], ['saved_spots', 'users'],
    ['passkeys', 'users'], ['sessions', 'users'], ['auth_challenges', 'users'], ['users', 'comfort_feedback'], ['comfort_feedback', 'd1_migrations']];
  for (const [a, b] of before) assert.ok(at(a) >= 0 && at(a) < at(b), `${a} is dropped before ${b}`);
  assert.equal(at('d1_migrations'), drops.length - 1);
  assert.ok(drops.every(n => !/^(sqlite_|_cf_)/.test(n)), 'no internal table is dropped');
  assert.doesNotMatch(sqlOf(RUNBOOK, 'clear'), /PRAGMA|foreign_keys/i);

  // CI runs the checker in the `check` job right after Node setup, with no web-area gate.
  const lines = read('.github/workflows/ci.yml').split('\n');
  const named = lines.map((l, i) => (l === '      - name: D1 restore runbook coverage' ? i : -1)).filter(i => i >= 0);
  assert.equal(named.length, 1, 'one coverage step');
  const start = named[0];
  const end = lines.findIndex((l, i) => i > start && /^( {6}- |  \S)/.test(l));
  const step = lines.slice(start, end);
  assert.deepEqual(step, ['      - name: D1 restore runbook coverage', '        run: node scripts/check_d1_restore.mjs'], 'no `if:` gate, nothing else in the step');
  const previous = lines.slice(0, start).reverse().filter(l => !/^\s*#/.test(l));
  assert.deepEqual(previous.slice(0, 3), ['          node-version: "22"', '        with:', previous[2]]);
  assert.match(previous[2], /^ {6}- uses: actions\/setup-node@[0-9a-f]{40} /, 'directly after Node setup');
  assert.equal(lines.slice(0, start).reverse().find(l => /^ {2}[a-z-]+:$/.test(l)), '  check:');
});
function util_equal(a, b) { return a.length === b.length && a.every((x, i) => x === b[i]); }

// ---- schema_addition_requires_all_three_sections --------------------------------------------
test('schema_addition_requires_all_three_sections', () => {
  const grown = SCHEMA + PROBE;
  const name = 'synthetic_restore_probe';
  assert.ok(parseSchemaTables(grown).tables.includes(name));
  assert.deepEqual(check(RUNBOOK, grown), ['inventory', 'counts', 'clear'].map(s => diag(s, `missing ${name}`)));
  const done = { inventory: adding('inventory', name), counts: adding('counts', name), clear: adding('clear', name) };
  for (const omitted of ['inventory', 'counts', 'clear']) {
    const others = ['inventory', 'counts', 'clear'].filter(s => s !== omitted);
    const runbook = others.reduce((text, s) => done[s](text), RUNBOOK);
    assert.deepEqual(check(runbook, grown), [diag(omitted, `missing ${name}`)], `only ${omitted} is reported`);
  }
  assert.deepEqual(check(['inventory', 'counts', 'clear'].reduce((text, s) => done[s](text), RUNBOOK), grown), []);

  // How declarations are read.
  const parsed = parseSchemaTables([
    "import {sqliteTable, text} from 'drizzle-orm/sqlite-core';",
    "export const a = sqliteTable('single_q', {id: text('id')});",
    'export const b = sqliteTable("double_q", {id: text("id")});',
    "export const c = sqliteTable(\n  'multi_line',\n  {id: text('id')},\n);",
    "// export const d = sqliteTable('commented_out', {});",
    "/* export const e = sqliteTable('block_commented', {}); */",
    "export const f = sqliteTable('it_is', {note: text('owner\\'s // not a comment')}); // owner's note",
  ].join('\n'));
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.tables, ['single_q', 'double_q', 'multi_line', 'it_is']);
  // Fail closed: nothing that cannot be read as a literal name may quietly shrink the list.
  for (const bad of ['sqliteTable(NAME, {})', 'sqliteTable(`tpl`, {})', "sqliteTable('a' + 'b', {})", "sqliteTable<Row>('typed', {})", 'const mk = sqliteTable;', "sqliteTableCreator('p_')('x', {})", "sqliteTable('bad name', {})"]) {
    const result = check(RUNBOOK, `${SCHEMA}\nexport const x = ${bad};\n`);
    assert.ok(result.length > 0 && result.every(l => l.startsWith(`${PREFIX}schema: `)), bad);
  }
  assert.deepEqual(parseSchemaTables('export const nothing = 1;').errors, ['no sqliteTable declarations found']);
  assert.match(parseSchemaTables("sqliteTable('twice', {}); sqliteTable('twice', {});").errors[0], /declared more than once: twice/);
});

// ---- wrong_duplicate_or_prose_only_name_fails -----------------------------------------------
test('wrong_duplicate_or_prose_only_name_fails', () => {
  for (const name of ['catch_log', 'saved_spots', 'advisor_media', 'fleet_runs']) {
    for (const section of ['inventory', 'counts', 'clear']) {
      assert.deepEqual(check(without(section, name)(RUNBOOK)), [diag(section, `missing ${name}`)], `${name} removed from ${section}`);
    }
    // The name left in prose, in a heading or in a later block does not count.
    const prose = without('inventory', name)(RUNBOOK) + `\nNotes: \`${name}\` is mentioned here only.\n`;
    assert.deepEqual(check(prose), [diag('inventory', `missing ${name}`)]);
  }
  const moved = without('clear', 'catch_log')(RUNBOOK) + '\n```bash\nDROP TABLE IF EXISTS catch_log;\n```\n';
  assert.deepEqual(check(moved), [diag('clear', 'missing catch_log')]);

  // Duplicates, extras and a wrong label or FROM.
  const duplicated = { inventory: row('catch_log'), counts: `\nUNION ALL ${select('catch_log')}`, clear: 'DROP TABLE IF EXISTS catch_log;\n' };
  assert.deepEqual(check(withBody(RUNBOOK, 'inventory', t => t + duplicated.inventory)), [diag('inventory', 'duplicate catch_log')]);
  assert.deepEqual(check(withBody(RUNBOOK, 'counts', t => t.replace(/;\n```/, `${duplicated.counts};\n\`\`\``))), [diag('counts', 'duplicate catch_log')]);
  assert.deepEqual(check(withBody(RUNBOOK, 'clear', t => t.replace(/\n```\s*$/, `\n${duplicated.clear}\`\`\`\n`))), [diag('clear', 'duplicate catch_log')]);
  for (const section of ['inventory', 'counts', 'clear']) assert.deepEqual(check(adding(section, 'not_in_schema')(RUNBOOK)), [diag(section, 'extra not_in_schema')], `${section} extra`);
  const relabelled = withBody(RUNBOOK, 'counts', t => t.replace("SELECT 'saved_spots' AS", "SELECT 'spots' AS"));
  assert.deepEqual(check(relabelled), [diag('counts', 'malformed block: label differs from FROM table: spots labelled for saved_spots')]);
  const reselected = withBody(RUNBOOK, 'counts', t => t.replace('FROM saved_spots', 'FROM catch_log'));
  assert.equal(check(reselected).length, 1);
  assert.match(check(reselected)[0], /label differs from FROM table: saved_spots labelled for catch_log/);

  // Unexpected SQL and malformed markers, each with its own section diagnostic.
  assert.match(check(withBody(RUNBOOK, 'counts', t => t.replace(/;\n```/, ';\nDROP TABLE users;\n```')))[0], new RegExp(`^${PREFIX}counts: malformed block: one statement terminated by a single ;`));
  assert.match(check(withBody(RUNBOOK, 'counts', t => t.replace("COUNT(*) AS row_count FROM users", 'COUNT(*) AS row_count FROM users WHERE 1')))[0], /counts: malformed block: unexpected SQL: SELECT 'users'/);
  assert.match(check(withBody(RUNBOOK, 'clear', t => t.replace('DROP TABLE IF EXISTS users;', 'DROP TABLE users;')))[0], /clear: malformed block: unexpected SQL: DROP TABLE users;/);
  assert.match(check(adding('clear', 'sqlite_sequence')(RUNBOOK))[0], /clear: malformed block: internal table sqlite_sequence must not be dropped/);
  assert.match(check(adding('clear', '_cf_KV'.toLowerCase())(RUNBOOK))[0], /internal table _cf_kv/);
  assert.match(check(withBody(RUNBOOK, 'clear', t => t.replace(/\n```\s*$/, '\n-- DROP TABLE IF EXISTS users;\n```\n')))[0], /clear: malformed block: unexpected SQL: -- DROP/);
  assert.match(check(withBody(RUNBOOK, 'inventory', t => t.replace('| Table |', '| Name |')))[0], /inventory: malformed block: header must be/);
  assert.match(check(withBody(RUNBOOK, 'inventory', t => t.replace('| `users` | Accounts', '| users | Accounts')))[0], /inventory: malformed block: row \d+ needs four cells/);
  assert.deepEqual(check(withBody(RUNBOOK, 'inventory', t => t.replace(/\| `request_limits` \| [^|]*\|/, '| `request_limits` | |'))).length, 1);
  for (const section of ['inventory', 'counts', 'clear']) {
    const none = RUNBOOK.replace(edge(section, 'start'), '');
    assert.deepEqual(check(none), [diag(section, 'malformed block: expected exactly one start and one end marker, found 0 and 1')]);
    const twice = RUNBOOK.replace(edge(section, 'end'), `${edge(section, 'end')}\n${edge(section, 'end')}`);
    assert.deepEqual(check(twice), [diag(section, 'malformed block: expected exactly one start and one end marker, found 1 and 2')]);
    assert.deepEqual(check(withBody(RUNBOOK, section, () => '\n\n')), [diag(section, 'malformed block: empty')]);
    const swapped = RUNBOOK.replace(edge(section, 'start'), '@@S@@').replace(edge(section, 'end'), edge(section, 'start')).replace('@@S@@', edge(section, 'end'));
    assert.ok(check(swapped).some(l => l.startsWith(diag(section, 'malformed block'))), `${section} markers swapped`);
  }
  assert.deepEqual(check(RUNBOOK.slice(0, 0)).map(l => l.split(': ')[2]), ['inventory', 'counts', 'clear']);
});

// ---- real local SQLite clear / import / count rehearsal -------------------------------------
const quote = v => v === null ? 'NULL' : typeof v === 'number' ? String(v) : `'${String(v).replaceAll("'", "''")}'`;
const ZERO = new Set(['request_limits', 'fleet_ais_hours']);

/** Seed every committed-migration table with synthetic rows, then clear, re-import and count with the runbook's own SQL. */
function rehearse(runbook) {
  assert.equal(sqliteUnavailable, null, 'node:sqlite must be available: the rehearsal may not skip');
  const {sql} = advisorDatabase();
  sql.exec('PRAGMA foreign_keys = ON');
  sql.exec('CREATE TABLE d1_migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)');
  for (const {tag} of journal().entries) sql.prepare('INSERT INTO d1_migrations(name) VALUES (?)').run(`${tag}.sql`);
  const tables = () => sql.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all().map(r => r.name);
  const names = tables();
  assert.ok(util_equal(names, [...schemaTables(), 'd1_migrations'].sort()), 'committed migrations create exactly the schema tables plus bookkeeping');
  names.filter(n => n !== 'd1_migrations').forEach((table, i) => {
    const columns = sql.prepare(`PRAGMA table_info(${table})`).all();
    const rows = ZERO.has(table) ? 0 : (i % 2) + 1;
    for (let n = 1; n <= rows; n++) {
      const values = columns.map(c => /int/i.test(c.type) ? n : /real/i.test(c.type) ? n + 0.5 : `${table}.${c.name}.${n}`);
      sql.prepare(`INSERT INTO ${table}(${columns.map(c => c.name).join(',')}) VALUES (${columns.map(() => '?').join(',')})`).run(...values);
    }
  });
  const count = () => Object.fromEntries(sql.prepare(sqlOf(runbook, 'counts')).all().map(r => [r.table_name, r.row_count]));
  const expected = Object.fromEntries(names.map(n => [n, sql.prepare(`SELECT COUNT(*) AS c FROM ${n}`).get().c]));
  for (const n of ['catch_log', 'saved_spots', 'users', 'advisor_contacts', 'fleet_vessels', 'd1_migrations']) assert.ok(expected[n] > 0, `${n} is seeded`);
  for (const n of ZERO) assert.equal(expected[n], 0);
  const dump = () => names.map(n => `${n}:${JSON.stringify(sql.prepare(`SELECT * FROM ${n} ORDER BY rowid`).all())}`).join('\n');
  const before = dump();

  // The export: what is actually in the database, as create/index statements then inserts.
  const parts = sql.prepare("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type='table' DESC, rowid").all().map(r => `${r.sql};`);
  for (const n of names) for (const r of sql.prepare(`SELECT * FROM ${n} ORDER BY rowid`).all()) parts.push(`INSERT INTO ${n}(${Object.keys(r).join(',')}) VALUES (${Object.values(r).map(quote).join(',')});`);
  const exported = parts.join('\n');

  sql.exec(sqlOf(runbook, 'clear'));
  const left = tables();
  try { sql.exec(exported); } catch (e) { throw new Error(`${e.message} (left after the clear: ${left.join(', ') || 'none'})`); }
  assert.deepEqual(left, [], 'the documented clear leaves no application or bookkeeping table');
  const after = count();
  assert.ok(util_equal(Object.keys(after).sort(), names), 'count query returns one row per table');
  const pairs = o => JSON.stringify(Object.entries(o).sort());
  assert.ok(pairs(after) === pairs(expected), 'counts equal the saved counts, zeros included');
  assert.ok(dump() === before, 'every seeded row, sentinel values included, is back');
  return {names, expected};
}

test('documented_clear_import_counts_roundtrip', () => {
  const {names, expected} = rehearse(RUNBOOK);
  assert.ok(names.length > 44);
  assert.equal(expected.request_limits, 0);
});

// ---- negative controls: a name-only check cannot certify a broken procedure -----------------
test('omitted_drop_breaks_roundtrip', () => {
  for (const name of ['catch_log', 'saved_spots', 'advisor_contacts', 'fleet_trips', 'd1_migrations']) {
    const broken = without('clear', name)(RUNBOOK);
    assert.deepEqual(check(broken), [diag('clear', `missing ${name}`)]);
    assert.throws(() => rehearse(broken), new RegExp(`table \`?${name}\`? already exists`));
  }
});

test('counts_query_has_no_omissions', () => {
  const broken = without('counts', 'fleet_trips')(RUNBOOK);
  assert.ok(broken.includes('`fleet_trips`') && broken.includes('DROP TABLE IF EXISTS fleet_trips;'), 'the name still appears elsewhere');
  assert.deepEqual(check(broken), [diag('counts', 'missing fleet_trips')]);
  assert.throws(() => rehearse(broken), /count query returns one row per table/);
});

// ---- checker_cli_is_read_only_and_fail_closed -----------------------------------------------
const tree = dir => readdirSync(dir, {recursive: true}).sort().join('\n');
const digest = dir => createHash('sha256').update(tree(dir)).update(readFileSync(join(dir, SCHEMA_PATH))).update(readFileSync(join(dir, RUNBOOK_PATH))).digest('hex');
function fixture(files) {
  const dir = mkdtempSync(join(tmpdir(), 'd1-restore-'));
  mkdirSync(join(dir, 'db'), {recursive: true}); mkdirSync(join(dir, 'docs/operations/runbooks'), {recursive: true});
  if (files.schema !== null) writeFileSync(join(dir, SCHEMA_PATH), files.schema ?? SCHEMA);
  if (files.runbook !== null) writeFileSync(join(dir, RUNBOOK_PATH), files.runbook ?? RUNBOOK);
  return dir;
}
// --permission: any write, child process or worker the checker tried would be denied, not just discouraged.
const run = (args, cwd) => spawnSync(process.execPath, ['--permission', `--allow-fs-read=${ROOT}`, `--allow-fs-read=${tmpdir()}`, SCRIPT, ...args], {cwd, encoding: 'utf8', timeout: 20000});

test('checker_cli_is_read_only_and_fail_closed', () => {
  const dirs = [];
  const root = files => { const d = fixture(files); dirs.push(d); return d; };
  try {
    const good = root({});
    const before = digest(good);
    const ok = run(['--root', good], tmpdir());
    assert.equal(ok.status, 0, ok.stderr);
    assert.equal(ok.stdout.trim(), SUCCESS_MESSAGE);
    assert.equal(ok.stderr, '');
    assert.equal(digest(good), before, 'inputs and directory unchanged');
    const home = run([], tmpdir());       // default root is the repository the script lives in, not the cwd
    assert.equal(home.status, 0, home.stderr);
    assert.equal(home.stdout.trim(), SUCCESS_MESSAGE);

    const bad = root({runbook: without('inventory', 'catch_log')(RUNBOOK)});
    const failed = run(['--root', bad], tmpdir());
    assert.equal(failed.status, 1);
    assert.equal(failed.stdout, '');
    assert.equal(failed.stderr.trim(), diag('inventory', 'missing catch_log'));
    const grown = root({schema: SCHEMA + PROBE});
    assert.equal(run(['--root', grown], tmpdir()).stderr.trim().split('\n').length, 3);

    for (const absent of [{schema: null}, {runbook: null}]) {
      const r = run(['--root', root(absent)], tmpdir());
      assert.equal(r.status, 1);
      assert.match(r.stderr, new RegExp(`^${PREFIX}cannot read input: ENOENT`));
    }
    assert.equal(run(['--root', root({schema: 'export const nothing = 1;'})], tmpdir()).status, 1);

    for (const flags of [['--bogus'], ['--root'], ['--root', '--root'], ['--root', good, '--root', good], [good], ['--root=' + good], ['--root', '']]) {
      const r = run(flags, tmpdir());
      assert.equal(r.status, 2, flags.join(' '));
      assert.equal(r.stdout, '');
      assert.match(r.stderr, /usage: node scripts\/check_d1_restore\.mjs \[--root PATH\]/);
    }
    assert.equal(digest(good), before);
  } finally { for (const d of dirs) rmSync(d, {recursive: true, force: true}); }

  // The source itself: text-only imports, no network, no processes, no SQL execution, no runtime schema import.
  const source = readFileSync(SCRIPT, 'utf8');
  assert.deepEqual([...source.matchAll(/^import .* from '([^']+)'/gm)].map(m => m[1]).sort(), ['node:fs', 'node:path', 'node:url']);
  assert.doesNotMatch(source.replace(/^\/\/.*$/gm, ''), /\bfetch\(|child_process|spawn|execSync|execFile|wrangler|node:sqlite|writeFile|process\.env|import\(/);
});
