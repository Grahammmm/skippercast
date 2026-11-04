// Fleet privacy contract over every query path (SC2222-10; threat model § 10.3 risk 5).
// Static and offline: reads server/**/*.ts as text, keeps every string/template literal that
// names fleet_vessels or fleet_operators (comments dropped, `${CONST}` expanded from a
// same-file string constant) and checks it by the file's class:
//   public - a read carries `${publicVesselSql(...)}` (active, listed, no removal request);
//            the one other read is data.ts's consent_status,consent_revoked_at operator lookup;
//   job    - a SELECT of email_business/phone_business carries the do-not-contact exclusion
//            or is a recorded entry in CONTACT_READS;
//   admin  - listed only (requireUser + requireAdmin; admins see unlisted rows by design).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
const ROOT = new URL('..', import.meta.url).pathname;
const FLEET = /\bfleet_(vessels|operators)\b/;
const CONTACT = /\b(email_business|phone_business)\b/;
const DNC_EXCLUDED = /outreach_status\s*(<>|!=)\s*'do-not-contact'|NOT EXISTS \([^)]*outreach_status\s*=\s*'do-not-contact'/;
const CONSENT_READ = /^SELECT consent_status, ?consent_revoked_at FROM fleet_operators WHERE id=\?$/;

const CLASS = Object.freeze({
  'server/advisor/pages/data.ts': ['public', '/boats/<slug> profile: vessel via publicVesselSql, operator consent only'],
  'server/advisor/pages/sitemap.ts': ['public', 'sitemap.xml lists public vessel slugs'],
  'server/fleet/go.ts': ['public', '/go/<slug> outbound link redirect'],
  'server/fleet/activity.ts': ['job', 'AIS activity ingest: matches known vessel ids'],
  'server/fleet/ids.ts': ['job', 'registry id derivation'],
  'server/fleet/jobs.ts': ['job', 'jobs runner snapshot export (outreach preparation)'],
  'server/fleet/leadscore.ts': ['job', 'operator lead scoring inputs'],
  'server/fleet/pairing.ts': ['job', 'AIS name pairing matcher'],
  'server/fleet/registry.ts': ['job', 'registry import writer'],
  'server/fleet/watch.ts': ['job', 'AIS watch list maintenance'],
  'server/fleet/map.ts': ['admin', 'admin fleet map, imported only by server/routes/admin.ts'],
  'server/fleet/admin/clicks.ts': ['admin', 'admin link-click report'],
  'server/fleet/admin/coverage.ts': ['admin', 'admin coverage report'],
  'server/fleet/admin/labels.ts': ['admin', 'admin trip labelling'],
  'server/fleet/admin/operators.ts': ['admin', 'admin operator and outreach console'],
  'server/fleet/admin/reviews.ts': ['admin', 'admin review queue'],
  'server/fleet/admin/vessels.ts': ['admin', 'admin vessel editor'],
});
// Job reads of contact columns without the do-not-contact exclusion, as main has them today (none since SC1322-01).
const CONTACT_READS = Object.freeze({});
// One pass: group 1 is a string or template literal; a comment matches without a group.
const LITERAL = /(`(?:\\[\s\S]|\$\{[^}]*\}|[^\\`])*`|'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*")|\/\/[^\n]*|\/\*[\s\S]*?\*\//g;

/** Every literal in `text` naming a fleet table: raw (whitespace collapsed) and with `${CONST}` expanded. */
export function statements(text) {
  const consts = new Map();
  for (const m of text.matchAll(/\bconst ([A-Z][A-Z0-9_]*) = ((?:'[^'\n]*'\s*\+?\s*)+);/g))
    consts.set(m[1], [...m[2].matchAll(/'([^'\n]*)'/g)].map(p => p[1]).join(''));
  const out = [];
  for (const m of text.matchAll(LITERAL)) {
    if (!m[1] || !FLEET.test(m[1])) continue;
    const raw = m[1].slice(1, -1).replace(/\s+/g, ' ').trim();
    out.push({raw, sql: raw.replace(/\$\{([A-Z][A-Z0-9_]*)\}/g, (s, name) => consts.get(name) ?? s)});
  }
  return out;
}
const contactKey = (file, raw) => `${file} ${(raw.match(/^.*?\bFROM fleet_(vessels|operators)\b/) ?? [raw])[0]}`;

/** Errors for one file's fleet statements under `cls`; `used` collects the CONTACT_READS keys it relied on. */
export function check(file, text, cls = CLASS, contact = CONTACT_READS, used = new Set()) {
  const found = statements(text);
  if (!found.length) return {found, errors: []};
  const kind = cls[file]?.[0];
  if (!kind) return {found, errors: [`classify ${file} in CLASS (admin, job or public) before reading fleet tables`]};
  const errors = [];
  for (const {raw, sql} of found) {
    if (kind === 'public' && !/\$\{publicVesselSql\(/.test(sql) && !(CONSENT_READ.test(sql) && !sql.includes('${')))
      errors.push(`${file}: public fleet read without publicVesselSql(): ${raw}`);
    if (kind === 'job' && /\bSELECT\b/i.test(sql) && CONTACT.test(sql) && !DNC_EXCLUDED.test(sql)) {
      const key = contactKey(file, raw);
      if (contact[key]) used.add(key);
      else errors.push(`${file}: job reads contact columns without the do-not-contact exclusion: ${raw}`);
    }
  }
  return {found, errors};
}

function* tsFiles(dir) {
  for (const entry of readdirSync(dir, {withFileTypes: true})) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* tsFiles(path);
    else if (entry.name.endsWith('.ts')) yield path.slice(ROOT.length);
  }
}

test('every server fleet query is classified and public/job reads keep the privacy filters', () => {
  const used = new Set(), errors = [], perFile = new Map();
  for (const file of tsFiles(join(ROOT, 'server'))) {
    const result = check(file, readFileSync(join(ROOT, file), 'utf8'), CLASS, CONTACT_READS, used);
    errors.push(...result.errors);
    perFile.set(file, result.found.length);
  }
  assert.deepEqual(errors, []);
  for (const [file, [kind]] of Object.entries(CLASS))  // a broken scan cannot pass silently
    if (kind === 'public') assert.ok(perFile.get(file) >= 1, `scan found no statement in ${file}`);
  assert.equal(perFile.get('server/fleet/display.ts'), 0, 'display.ts names the tables in comments only');
  assert.deepEqual(Object.keys(CONTACT_READS).filter(k => !used.has(k)), [], 'stale CONTACT_READS entry');
});

const PUB = {'x/pub.ts': ['public', 'synthetic']}, JOB = {'x/job.ts': ['job', 'synthetic']};
const errs = (file, text, cls, contact = {}) => check(file, text, cls, contact).errors;

test('a public read without publicVesselSql fails with the file name, also when only worded like it', () => {
  for (const text of ["db.prepare('SELECT slug FROM fleet_vessels WHERE id=?')",
    "q(`SELECT slug FROM fleet_vessels WHERE id=? -- publicVesselSql()`)", "q('SELECT slug FROM fleet_vessels WHERE publicVesselSql(')",
    "q('SELECT consent_status,consent_revoked_at,email_business FROM fleet_operators WHERE id=?')"]) {
    const e = errs('x/pub.ts', text, PUB);
    assert.equal(e.length, 1, text);
    assert.match(e[0], /^x\/pub\.ts: public fleet read without publicVesselSql\(\)/);
  }
  assert.deepEqual(errs('x/pub.ts', "q(`SELECT v.slug FROM fleet_vessels v WHERE ${publicVesselSql('v')}`)", PUB), [], 'aliased form');
  assert.deepEqual(errs('x/pub.ts', 'q(`SELECT id FROM fleet_vessels WHERE slug=? AND ${publicVesselSql()}`)', PUB), []);
  assert.deepEqual(errs('x/pub.ts', "q('SELECT consent_status,consent_revoked_at FROM fleet_operators WHERE id=?')", PUB), []);
});

test('an unclassified file reading fleet_operators fails with the classify message', () => {
  assert.deepEqual(errs('server/new.ts', 'q(`SELECT id FROM fleet_operators`)', {}),
    ['classify server/new.ts in CLASS (admin, job or public) before reading fleet tables']);
});

test('a job contact read needs the do-not-contact exclusion or a CONTACT_READS entry', () => {
  const dnc = "const DNC = 'do-not-contact';\n";
  const bare = 'q(`SELECT id,email_business FROM fleet_operators WHERE region=?`)';
  assert.equal(errs('x/job.ts', bare, JOB).length, 1);
  assert.equal(errs('x/job.ts', dnc + "q(`SELECT id,phone_business FROM fleet_operators WHERE outreach_status='${DNC}'`)", JOB).length, 1, 'selecting DNC rows is no exclusion');
  assert.equal(errs('x/job.ts', "const COLS = 'id,' +\n  'email_business';\nq(`SELECT ${COLS} FROM fleet_vessels`)", JOB).length, 1, 'columns hidden in a constant');
  assert.deepEqual(errs('x/job.ts', dnc + "q(`SELECT id,email_business FROM fleet_operators WHERE outreach_status<>'${DNC}'`)", JOB), []);
  assert.deepEqual(errs('x/job.ts', bare, JOB, {'x/job.ts SELECT id,email_business FROM fleet_operators': 'reason'}), []);
  assert.deepEqual(errs('x/job.ts', bare, {'x/job.ts': ['admin', 'synthetic']}), [], 'admin is listed only');
});

test('comments naming the fleet tables are not statements', () => {
  const text = "// public (display.ts publicVesselSql: `status='active'`) fleet_vessels\n/* fleet_operators `x` it's */ const a = 'b';";
  assert.deepEqual(check('x/none.ts', text, {}), {found: [], errors: []});
});
