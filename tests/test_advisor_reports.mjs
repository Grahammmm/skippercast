// Skipper fish reports (server/advisor/intake/reports.ts, the read_count_board,
// propose_report and edit_report tools, the engine's report flow and the
// consumer's report appliers; docs/plans/text-advisor/05-skipper-intake.md
// § Count-board photo → report, § Plain-text report, § Catch and action photos,
// § Corrections, § Auto-publish; 04 § stage 2). The grammar tables (40 count
// texts and 20 corrections, en and es), the board date rule and "?" lines, the
// confirmation shape, then the flows through the consumer: y / n / correction /
// anything else, the same-day report as an edit, clean_reports, AUTO / ASK ME,
// the pages version and the daily answer, and the media path by kind with the
// recorded vision fixtures (consent, no consent, has_person, video, too large).
// The scripted golden conversations 2 and 3 run in tests/test_advisor_engine.mjs.
// Offline: real migrations in node:sqlite, a memory R2, recorded vision answers.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const r = await import('../server/advisor/intake/reports.ts');
const {runTurn, engineHandler, STAGE_TWO_FLOWS} = await import('../server/advisor/engine.ts');
const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {STRINGS, t} = await import('../server/advisor/strings.ts');
const {reviewId} = await import('../server/advisor/contacts.ts');
const {visionChain} = await import('../server/advisor/vision/index.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T17:00:00Z');   // Saturday 10:00 in Morro Bay
const TODAY = '2026-10-03';
const HOUR = 3600000, DAY = 24 * HOUR;
const KEY = Buffer.alloc(32, 7).toString('base64');
const iso = ms => new Date(ms).toISOString();
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const vfixture = name => read(`./fixtures/advisor/vision/${name}`);
const png = name => readFileSync(new URL(`./fixtures/advisor/vision/images/${name}`, import.meta.url));

// ---- the grammar tables (10 § TA-I2) ------------------------------------------------------------

// [text, expected]: expected is null (not a report) or {anglers, trip, day, counts: [[label, species_key, kept, released]], notes}.
const C = (label, key, kept, released = null) => [label, key, kept, released];
const COUNT_TEXTS = [
  // English
  ['22 anglers, 45 vermilion, 12 lings', {anglers: 22, counts: [C('vermilion', 'rockfish', 45), C('lings', 'lingcod', 12)]}],
  ['22 anglers\n45 vermilion\n12 lingcod (2 rel)\n8 copper\n3 cabezon', {anglers: 22, counts: [C('vermilion', 'rockfish', 45), C('lingcod', 'lingcod', 12, 2), C('copper', 'rockfish', 8), C('cabezon', 'cabezon', 3)]}],
  ['Full day, 22 pax: 45 reds, 12 lings (2 released), 8 coppers, 3 cabbies', {anglers: 22, trip: 'full-day', counts: [C('reds', 'rockfish', 45), C('lings', 'lingcod', 12, 2), C('coppers', 'rockfish', 8), C('cabbies', 'cabezon', 3)]}],
  ['half day 18 people 60 rockfish 4 lings', {anglers: 18, trip: 'half-day', counts: [C('rockfish', 'rockfish', 60), C('lings', 'lingcod', 4)]}],
  ['45 vermilion, 12 lingcod', {counts: [C('vermilion', 'rockfish', 45), C('lingcod', 'lingcod', 12)]}],
  ['30 rock cod and 6 lings', {counts: [C('rock cod', 'rockfish', 30), C('lings', 'lingcod', 6)]}],
  ['yesterday 15 anglers 70 rockfish 10 lings 2 released', {anglers: 15, day: -1, counts: [C('rockfish', 'rockfish', 70), C('lings', 'lingcod', 10, 2)]}],
  ['overnight trip, 12 anglers, 24 yellowtail, 10 bluefin, 3 yft', {anglers: 12, trip: 'overnight', counts: [C('yellowtail', 'yellowtail', 24), C('bluefin', 'bluefin', 10), C('yft', 'yellowfin', 3)]}],
  ['20 pax 100 rcg 9 lings 1 cabezon', {anglers: 20, counts: [C('rcg', 'rockfish', 100), C('lings', 'lingcod', 9), C('cabezon', 'cabezon', 1)]}],
  ['12 halis, 4 WSB', {counts: [C('halis', 'halibut', 12), C('WSB', 'white-seabass', 4)]}],
  ['22 anglers, limits of rockfish, 12 lings', {anglers: 22, counts: [C('lings', 'lingcod', 12)], notes: 'limits of rockfish'}],
  ['22 anglers. 45 vermilion. 12 lings.', {anglers: 22, counts: [C('vermilion', 'rockfish', 45), C('lings', 'lingcod', 12)]}],
  ['45 vermilion; 12 lingcod; 8 copper', {counts: [C('vermilion', 'rockfish', 45), C('lingcod', 'lingcod', 12), C('copper', 'rockfish', 8)]}],
  ['6 anglers', {anglers: 6, counts: []}],
  ['25 Anglers 120 Rockfish 15 Lingcod 3 Cabezon', {anglers: 25, counts: [C('Rockfish', 'rockfish', 120), C('Lingcod', 'lingcod', 15), C('Cabezon', 'cabezon', 3)]}],
  ['10 crab, 40 rockfish', {counts: [C('crab', 'dungeness', 10), C('rockfish', 'rockfish', 40)]}],
  ['12 lingcod 3 released, 40 rockfish', {counts: [C('lingcod', 'lingcod', 12, 3), C('rockfish', 'rockfish', 40)]}],
  ['40 rockfish, 2 lings released', {counts: [C('rockfish', 'rockfish', 40), C('lings', 'lingcod', 0, 2)]}],
  ['22 anglers, 45 vermilion, 12 lings, water 58 degrees, great day', {anglers: 22, counts: [C('vermilion', 'rockfish', 45), C('lings', 'lingcod', 12)], notes: 'water 58 degrees; great day'}],
  ['good day, 3 hrs, 40 rockfish, 5 lings', {counts: [C('rockfish', 'rockfish', 40), C('lings', 'lingcod', 5)], notes: 'good day; 3 hrs'}],
  ['8 sheephead 20 calico', {counts: [C('sheephead', 'sheephead', 8), C('calico', 'kelp-bass', 20)]}],
  ['22 anglers 45 vermilion 12 lings 8 coppers 3 cabezon 2 greenling', {anglers: 22, counts: [C('vermilion', 'rockfish', 45), C('lings', 'lingcod', 12), C('coppers', 'rockfish', 8), C('cabezon', 'cabezon', 3), C('greenling', 'kelp-greenling', 2)]}],
  ['Today: 16 people, 64 rockfish, 7 lings (1 rel)', {anglers: 16, day: 0, counts: [C('rockfish', 'rockfish', 64), C('lings', 'lingcod', 7, 1)]}],
  ['3 halibut + 2 white seabass', {counts: [C('halibut', 'halibut', 3), C('white seabass', 'white-seabass', 2)]}],
  ['18 anglers 54 rockfish 6 lingcod 4 mystery fish', {anglers: 18, counts: [C('rockfish', 'rockfish', 54), C('lingcod', 'lingcod', 6), C('mystery fish', 'other', 4)]}],
  ['1 halibut', null],
  ['what time do you open?', null],
  ['we caught 12 fish', null],
  // Spanish
  ['18 personas, 50 rocotes, 6 lingcod', {anglers: 18, counts: [C('rocotes', 'rockfish', 50), C('lingcod', 'lingcod', 6)]}],
  ['ayer 20 pescadores, 80 colorados, 10 lingcod', {anglers: 20, day: -1, counts: [C('colorados', 'rockfish', 80), C('lingcod', 'lingcod', 10)]}],
  ['medio día, 15 personas, 40 rocotes y 5 cabezones', {anglers: 15, trip: 'half-day', counts: [C('rocotes', 'rockfish', 40), C('cabezones', 'cabezon', 5)]}],
  ['día completo 22 personas 45 colorados 12 lingcod (2 liberados)', {anglers: 22, trip: 'full-day', counts: [C('colorados', 'rockfish', 45), C('lingcod', 'lingcod', 12, 2)]}],
  ['30 rocotes, 4 lenguados', {counts: [C('rocotes', 'rockfish', 30), C('lenguados', 'halibut', 4)]}],
  ['nocturno 10 personas 20 jureles 5 atún aleta azul', {anglers: 10, trip: 'overnight', counts: [C('jureles', 'yellowtail', 20), C('atún aleta azul', 'bluefin', 5)]}],
  ['hoy 12 personas: 36 rocotes, 4 lingcod, 2 cabezones', {anglers: 12, day: 0, counts: [C('rocotes', 'rockfish', 36), C('lingcod', 'lingcod', 4), C('cabezones', 'cabezon', 2)]}],
  ['25 personas\n100 rocotes\n12 lingcod 3 liberados', {anglers: 25, counts: [C('rocotes', 'rockfish', 100), C('lingcod', 'lingcod', 12, 3)]}],
  ['10 cangrejos y 30 rocotes', {counts: [C('cangrejos', 'dungeness', 10), C('rocotes', 'rockfish', 30)]}],
  ['14 pescadores, 6 corvina blanca, 2 jureles', {anglers: 14, counts: [C('corvina blanca', 'white-seabass', 6), C('jureles', 'yellowtail', 2)]}],
  ['20 personas, 40 colorados, buen día', {anglers: 20, counts: [C('colorados', 'rockfish', 40)], notes: 'buen día'}],
  ['¿a qué hora salen mañana?', null],
];

test('parseCountText: the 40 count-text phrasings (en/es) of 10 § TA-I2', () => {
  assert.equal(COUNT_TEXTS.length, 40);
  assert.ok(COUNT_TEXTS.filter(([x]) => /personas|pescadores|rocotes|colorados|cangrejos|hora/.test(x)).length >= 12, 'Spanish phrasings');
  for (const [text, want] of COUNT_TEXTS) {
    const got = r.parseCountText(text);
    if (want === null) { assert.equal(got, null, text); assert.equal(r.looksLikeCountText(text), false, text); continue; }
    assert.ok(got, text);
    assert.deepEqual({
      anglers: got.anglers, trip: got.trip_type, day: got.day_offset, notes: got.notes,
      counts: got.counts.map(c => [c.label, c.species_key, c.kept, c.released]),
    }, {anglers: want.anglers ?? null, trip: want.trip ?? null, day: want.day ?? null, notes: want.notes ?? null, counts: want.counts}, text);
    assert.equal(r.looksLikeCountText(text), true, `${text}: the pre-router takes it`);
  }
});

test('the pre-router: "<n> anglers" or two species pairs; chat with numbers stays with the model', () => {
  for (const yes of ['6 anglers', '22 pax', '15 personas, 30 rocotes', '45 vermilion 12 lings']) assert.ok(r.looksLikeCountText(yes), yes);
  for (const no of ['is 12 lb line ok for 2 lings?', 'leaving at 6 am, back at 3 pm', 'how many lings can I keep', '2 boats out today', 'x'.repeat(700) + ' 6 anglers']) assert.ok(!r.looksLikeCountText(no), no);
  assert.ok(r.COUNT_TRIGGER.test('22 anglers') && r.COUNT_TRIGGER.test('18 personas') && !r.COUNT_TRIGGER.test('anglers'));
});

// The report a correction applies to: 05's example board.
const BASE = {report_date: TODAY, trip_type: 'full-day', anglers: 22, notes: null, counts: [
  {species_key: 'rockfish', label: 'vermilion', kept: 45, released: null},
  {species_key: 'lingcod', label: 'lingcod', kept: 12, released: 2},
  {species_key: 'rockfish', label: 'copper', kept: 8, released: null},
  {species_key: 'cabezon', label: 'cabezon', kept: 3, released: null, uncertain: true}]};

// [text, the corrected-line reply (05: "Updated: ..."), the fields that change]
const CORRECTIONS = [
  ['lings were 14', 'Updated: 14 lingcod (2 released).', ['counts']],
  ['lingcod 14', 'Updated: 14 lingcod (2 released).', ['counts']],
  ['lingcod: 14', 'Updated: 14 lingcod (2 released).', ['counts']],
  ['lings = 14 (3 rel)', 'Updated: 14 lingcod (3 released).', ['counts']],
  ['vermilion was 40', 'Updated: 40 vermilion.', ['counts']],
  ['reds 40', 'Updated: 40 vermilion.', ['counts']],
  ['40 vermilion', 'Updated: 40 vermilion.', ['counts']],
  ['add 2 halibut', 'Updated: 2 halibut.', ['counts']],
  ['add 3 lings', 'Updated: 15 lingcod (2 released).', ['counts']],
  ['remove cabezon', 'Updated: cabezon removed.', ['counts']],
  ['20 anglers', 'Updated: 20 anglers.', ['anglers']],
  ['it was yesterday', 'Updated: Fri Oct 2.', ['report_date']],
  ['it was 10/2', 'Updated: Fri Oct 2.', ['report_date']],
  ['half day', 'Updated: half day.', ['trip_type']],
  ['actually lings were 14 and cabezon 4', 'Updated: 14 lingcod (2 released), 4 cabezon.', ['counts']],
  ['los lingcod eran 14', 'Actualizado: 14 lingcod (2 liberados).', ['counts']],
  ['colorados 40', 'Actualizado: 40 vermilion.', ['counts']],
  ['quita cabezon', 'Actualizado: cabezon quitado.', ['counts']],
  ['fueron 20 personas', 'Actualizado: 20 pescadores.', ['anglers']],
  ['fue ayer', 'Actualizado: vie 2 oct.', ['report_date']],
];

test('parseCorrection: the 20 correction phrasings (en/es) of 10 § TA-I2', () => {
  assert.equal(CORRECTIONS.length, 20);
  for (const [text, reply, changed] of CORRECTIONS) {
    const c = r.parseCorrection(text, BASE, TODAY);
    assert.ok(c, text);
    const language = reply.startsWith('Actualizado') ? 'es' : 'en';
    assert.equal(r.correctionText(c.changes, language), reply, text);
    assert.deepEqual(c.patch.map(p => p.field).sort(), [...changed].sort(), text);
    for (const p of c.patch) assert.notDeepEqual(p.from, p.to, `${text}: a patch entry changes something`);
  }
  // A corrected line loses its "?"; the others keep theirs.
  const fixed = r.parseCorrection('cabezon were 4', BASE, TODAY).fields.counts;
  assert.equal(fixed.find(c => c.label === 'cabezon').uncertain, undefined);
  assert.equal(r.parseCorrection('lings 14', BASE, TODAY).fields.counts.find(c => c.label === 'cabezon').uncertain, true);
});

test('parseCorrection: chat, other numbers, unknown lines and ambiguous species are not corrections', () => {
  for (const no of ['any reds over 5?', 'water was 58', 'what time tomorrow', 'thanks', 'great trip', 'rockfish 50', 'remove the halibut', 'it was 12/25', 'it was last month',
    'we left at 6', 'lings were great']) assert.equal(r.parseCorrection(no, BASE, TODAY), null, no);
  // "rockfish 50" names two rockfish lines (vermilion, copper): ambiguous, so the model handles it with edit_report.
  const one = {...BASE, counts: [{species_key: 'rockfish', label: 'vermilion', kept: 45, released: null}]};
  assert.equal(r.correctionText(r.parseCorrection('rockfish 50', one, TODAY).changes, 'en'), 'Updated: 50 vermilion.', 'one rockfish line: that one');
});

test('dates: yesterday, weekdays, M/D and month names within 7 days; formatted en and es', () => {
  const cases = {today: TODAY, hoy: TODAY, yesterday: '2026-10-02', ayer: '2026-10-02', friday: '2026-10-02', saturday: TODAY, jueves: '2026-10-01', '10/1': '2026-10-01', '2026-09-28': '2026-09-28',
    'oct 1': '2026-10-01', '1 de oct': '2026-10-01', '9/26': '2026-09-26', '9/25': null, '10/4': null, 'oct 30': null, '2/30': null};
  for (const [words, want] of Object.entries(cases)) assert.equal(r.parseDateWords(words, TODAY), want, words);
  assert.equal(r.parseDateWords('dec 30', '2027-01-02'), '2026-12-30', 'last year across New Year');
  assert.equal(r.formatDate(TODAY, 'en'), 'Sat Oct 3');
  assert.equal(r.formatDate(TODAY, 'es'), 'sáb 3 oct');
});

// ---- count board -> draft, the confirmation text --------------------------------------------

const reading = (over = {}) => ({boat_name: 'Rita G', date_text: null, date_iso: null, date_confidence: 0, trip_type: 'Full Day', anglers: 22,
  lines: [{label: 'Vermilion', count: 45, released: null, confidence: 0.93}, {label: 'Lingcod', count: 12, released: 2, confidence: 0.9},
    {label: 'Copper', count: 8, released: null, confidence: 0.88}, {label: 'Cabezon', count: 3, released: null, confidence: 0.86}],
  notes: null, overall_confidence: 0.87, provider: 'claude', model: 'm', ms: 1, ...over});
const BOAT = {region: 'morro-bay'};

test('draftFromBoard: the date rule (confidence >= 0.8 and within 3 days, else today), labels kept, species keys', () => {
  const at = (date_iso, date_confidence) => r.draftFromBoard(reading({date_iso, date_confidence}), {id: 'c1'}, BOAT, T0).report_date;
  assert.equal(at(null, 0), TODAY, 'no date read: today');
  assert.equal(at('2026-10-02', 0.9), '2026-10-02', 'yesterday, read clearly');
  assert.equal(at('2026-09-30', 0.8), '2026-09-30', 'three days back, at the threshold');
  assert.equal(at('2026-09-29', 0.95), TODAY, 'four days back: today');
  assert.equal(at('2026-10-02', 0.79), TODAY, 'below 0.8: today');
  assert.equal(at('2026-10-04', 0.99), TODAY, 'a future date: today');
  assert.equal(r.draftFromBoard(reading(), null, BOAT, Date.parse('2026-10-04T06:30:00Z')).report_date, TODAY, 'today is the boat\'s local day (23:30 Pacific)');
  const d = r.draftFromBoard(reading({lines: [...reading().lines, {label: 'Sculpin', count: 6, released: null, confidence: 0.9}, {label: 'WSB', count: 1, released: null, confidence: 0.9}]}), null, BOAT, T0);
  assert.deepEqual(d.counts.map(c => [c.label, c.species_key]), [['Vermilion', 'rockfish'], ['Lingcod', 'lingcod'], ['Copper', 'rockfish'], ['Cabezon', 'cabezon'], ['Sculpin', 'other'], ['WSB', 'white-seabass']]);
  assert.equal(d.trip_type, 'full-day'); assert.equal(d.anglers, 22);
  assert.equal(d.counts.some(c => c.uncertain), false, 'an accepted reading has no "?"');
});

test('uncertain lines get "?" in the confirmation: low line confidence and unreadable counts; the 05 shape exactly', () => {
  const d = r.draftFromBoard(reading({lines: [{label: 'Vermilion', count: 45, released: null, confidence: 0.93}, {label: 'Lingcod', count: 12, released: 2, confidence: 0.6},
    {label: 'Copper', count: null, released: null, confidence: 0.4}]}), null, BOAT, T0);
  assert.deepEqual(d.counts.map(c => Boolean(c.uncertain)), [false, true, true]);
  assert.equal(r.confirmationText({...d, boat_name: 'Rita G'}, 'en'),
    'Rita G, Sat Oct 3, full day, 22 anglers:\n45 vermilion, 12? lingcod (2 released), ? copper\nReply Y to post, or tell me what to fix.');
  const full = r.draftFromBoard(reading(), null, BOAT, T0);
  assert.equal(r.confirmationText({...full, boat_name: 'Rita G'}, 'en'),
    'Rita G, Sat Oct 3, full day, 22 anglers:\n45 vermilion, 12 lingcod (2 released), 8 copper, 3 cabezon\nReply Y to post, or tell me what to fix.', '05 § count board step 3, word for word');
  assert.equal(r.confirmationText({...full, boat_name: 'Rita G'}, 'es'),
    'Rita G, sáb 3 oct, día completo, 22 pescadores:\n45 vermilion, 12 lingcod (2 liberados), 8 copper, 3 cabezon\nResponde SÍ para publicar, o dime qué corregir.');
  assert.equal(r.confirmationText({report_date: TODAY, trip_type: null, anglers: null, counts: [], notes: 'slow day', boat_name: 'Lucero'}, 'en'),
    'Lucero, Sat Oct 3:\nno counts yet\nNotes: slow day\nReply Y to post, or tell me what to fix.');
});

// ---- the flows through the consumer --------------------------------------------------------------

function setup({contact = {}, boat = {}, env = {}} = {}) {
  const {sql, db} = advisorDatabase();
  const c = {id: 'c1', phone_hash: 'h1', phone_enc: 'ENC', channel: 'imessage', role: 'skipper', language: 'en', boat_id: 'b1', ...contact};
  addContact(sql, c);
  const b = {id: 'b1', slug: 'rita-g', name: 'Rita G', owner: 'c1', status: 'pending', consent: null, instagram: null, clean: 0, auto: 0, ...boat};
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,consent_photos_at,instagram,clean_reports,auto_publish,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay',?,?,?,?,?,?,?,?)`)
    .run(b.id, b.slug, b.name, b.owner, b.status, b.consent, b.instagram, b.clean, b.auto, iso(T0 - 30 * DAY), iso(T0 - 30 * DAY));
  const bucket = memoryBucket();
  return {sql, db, bucket, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_NUMBER: '+15555550199', ADVISOR_PHONE_KEY: KEY, ADVISOR_MEDIA: bucket, ANTHROPIC_API_KEY: 'k', ADVISOR_VISION_PROVIDERS: 'claude', ...env}};
}
function addContact(sql, c) {
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'active',?,?,?)`)
    .run(c.id, c.phone_hash, c.phone_enc, c.channel ?? 'imessage', c.role ?? 'angler', c.language ?? 'en', c.boat_id ?? null, iso(T0), iso(T0), iso(T0));
  // Seen before, so no first-contact welcome.
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES(?,?,'in','imessage','earlier','done',?)`).run(`seen-${c.id}`, c.id, iso(T0 - 30 * DAY));
}
let seq = 0;
function inbound(sql, body, {contact = 'c1', media = null, at = T0, status = 'queued'} = {}) {
  const id = `in${++seq}`;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,created_at) VALUES(?,?,'in','imessage',?,?,?,?)`).run(id, contact, body, media ? JSON.stringify(media) : null, status, iso(at));
  return sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get(id);
}
/** A stored photo (already downloaded) for a contact: the media row and its bytes in R2. */
function addMedia(sql, bucket, {id, contact = 'c1', boat = 'b1', kind = 'image', mime = 'image/png', bytes = png('count-board.png'), state = 'private'}) {
  const key = kind === 'unknown' ? '' : `advisor/media/${contact}/${id}.${mime.split('/')[1]}`;
  if (key) bucket.objects.set(key, {bytes: new Uint8Array(bytes), httpMetadata: {}});
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES(?,?,?,?,?,?,?,'x',?,?)`)
    .run(id, contact, boat, kind, mime, bytes.length, key, state, iso(T0));
  return id;
}
/** A fake Messages API that answers the vision tools from fixtures (by tool name) and records the calls. */
function visionApi(answers) {
  const calls = [];
  return {calls, fetcher: async (_url, init) => {
    const body = JSON.parse(init.body); const name = body.tool_choice?.name; calls.push(name);
    const answer = answers[name];
    if (!answer) throw Error(`no vision answer for ${name}`);
    return new Response(JSON.stringify(answer), {status: 200, headers: {'content-type': 'application/json'}});
  }};
}
const BOARD = {record_classification: vfixture('classify-count-board.json'), record_count_board: vfixture('count-board.json')};
const PERSON = {record_classification: vfixture('classify-deck-person.json')};
const FISH = {record_classification: {...vfixture('classify-deck-person.json'), content: [{type: 'tool_use', id: 'x', name: 'record_classification',
  input: {kind: 'fish', kind_confidence: 0.92, has_person: false, person_confidence: 0.05, has_fish: true, text_present: false, nsfw: false}}]}};
let sends = 0;
function recorder() { const sent = []; return {sent, name: 'bluebubbles', async send(m) { sent.push(structuredClone(m)); return {providerId: `p${++sends}`, status: 'sent'}; }}; }
function batchOf(id) { return {queue: ADVISOR_QUEUE_NAME, messages: [{id: 'm', body: {message_id: id}, attempts: 1, ack() {}, retry() {}}], ackAll() {}, retryAll() {}}; }
/** One message through the consumer and the engine. Returns the texts sent and the stored inbound row. */
async function say(env, sql, body, {contact = 'c1', media = null, at = T0, vision = {}, api = null, ch = recorder()} = {}) {
  const m = inbound(sql, body, {contact, media, at});
  const v = visionApi(vision);
  const fetcher = api ? async (url, init) => (JSON.parse(init.body).tool_choice ? v.fetcher(url, init) : api(url, init)) : v.fetcher;
  const {lines} = await quiet(() => consumeAdvisor(batchOf(m.id), env, {channelFor: () => ch, handler: engineHandler, now: () => at, engine: {fetcher, clock: () => at, sleep: async () => {}}}));
  const row = sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get(m.id);
  assert.equal(row.status, 'done', `"${body}": ${row.status} ${row.error}`);
  return {texts: ch.sent.map(x => x.text), intent: row.intent, status: row.status, lines, visionCalls: v.calls, m};
}
const report = (sql, where = '1=1') => sql.prepare(`SELECT * FROM advisor_reports WHERE ${where} ORDER BY created_at DESC LIMIT 1`).get();
const boatRow = sql => sql.prepare("SELECT * FROM advisor_boats WHERE id='b1'").get();
const pagesVersion = sql => sql.prepare("SELECT value FROM job_state WHERE key='advisor.pages.version'").get()?.value ?? null;
const CONFIRM_TEXT = 'Rita G, Sat Oct 3, 22 anglers:\n45 vermilion, 12 lingcod (2 released), 8 copper, 3 cabezon\nReply Y to post, or tell me what to fix.';

dbTest('count text -> pending report and the confirmation; Y publishes: verified frozen, clean_reports + 1, pages version, the port\'s daily answer invalidated', async () => {
  const {sql, env} = setup({boat: {status: 'verified'}});
  for (const key of ['morro-bay:2026-10-03', 'morro-bay:2026-10-02', 'port-san-luis:2026-10-03']) sql.prepare("INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES(?,'x','x','h',?)").run(key, iso(T0));
  const a = await say(env, sql, '22 anglers\n45 vermilion\n12 lingcod (2 rel)\n8 copper\n3 cabezon');
  assert.equal(a.intent, 'report.text');
  assert.deepEqual(a.texts, [CONFIRM_TEXT]);
  const row = report(sql);
  assert.deepEqual([row.status, row.source, row.report_date, row.anglers, row.port, row.region, row.contact_id, row.version, row.verified], ['pending_confirm', 'text', TODAY, 22, 'morro-bay', 'morro-bay', 'c1', 1, 0]);
  assert.deepEqual(JSON.parse(row.counts_json)[1], {species_key: 'lingcod', label: 'lingcod', kept: 12, released: 2});
  assert.equal(pagesVersion(sql), null, 'nothing public yet');
  const y = await say(env, sql, 'Y', {at: T0 + 60000});
  assert.equal(y.intent, 'report.confirm');
  assert.deepEqual(y.texts, ['Posted. https://skippercast.com/boats/rita-g?s=txt']);
  const pub = report(sql);
  assert.deepEqual([pub.status, pub.verified, pub.confirmed_at, pub.published_at], ['published', 1, iso(T0 + 60000), iso(T0 + 60000)]);
  assert.equal(boatRow(sql).clean_reports, 1);
  assert.equal(pagesVersion(sql), '1');
  assert.deepEqual(sql.prepare('SELECT key FROM advisor_daily_answers ORDER BY key').all().map(x => x.key), ['port-san-luis:2026-10-03'], 'only this port\'s answers go');
  // The published report is what get_port_report serves (06), credited to the verified boat.
  const port = await TOOL_BY_NAME.get('get_port_report').run({port: 'morro-bay'}, {env, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: {id: 'x'}, deps: {feeds: async () => null},
    db: env.DB, language: 'en', settings: advisorSettings(env), now: T0 + 60000});
  assert.deepEqual(port.result.skipper_reports.map(x => [x.boat, x.date, x.anglers, x.counts.length]), [['Rita G', TODAY, 22, 4]]);
  // A redelivered "Y" does nothing twice.
  sql.prepare("UPDATE advisor_messages SET status='queued' WHERE id=?").run(y.m.id);
  await quiet(() => consumeAdvisor(batchOf(y.m.id), env, {channelFor: () => recorder(), handler: engineHandler, now: () => T0 + 60000, engine: {clock: () => T0 + 60000}}));
  assert.deepEqual([boatRow(sql).clean_reports, pagesVersion(sql)], [1, '1']);
  // A later "y" with nothing pending is not a confirmation.
  const later = await quiet(() => runTurn({env: {...env, ANTHROPIC_API_KEY: undefined}, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: inbound(sql, 'y', {at: T0 + HOUR}), now: T0 + HOUR, deps: {}}));
  assert.equal(later.value.intent, 'unconfigured');
});

dbTest('an unverified boat\'s report publishes with verified = 0 (frozen), and get_port_report calls it "a boat"', async () => {
  const {sql, env} = setup();
  await say(env, sql, '22 anglers, 45 vermilion, 12 lings');
  await say(env, sql, 'yes', {at: T0 + 1000});
  assert.deepEqual([report(sql).status, report(sql).verified], ['published', 0]);
  sql.prepare("UPDATE advisor_boats SET status='verified'").run();
  assert.equal(report(sql).verified, 0, 'verifying the boat later does not rewrite the frozen flag');
});

dbTest('N withdraws; a correction edits (edits row, version, confirmed_at cleared, clean_reports reset) and asks again; anything else goes to the model with the report in the brief', async () => {
  const {sql, env} = setup({boat: {clean: 3}});
  await say(env, sql, '22 anglers, 45 vermilion, 12 lings');
  const fix = await say(env, sql, 'lings were 14', {at: T0 + 1000});
  assert.equal(fix.intent, 'report.edit');
  assert.deepEqual(fix.texts, ['Updated: 14 lings. Reply Y to post, or tell me what to fix.'], 'the skipper\'s own label');
  const row = report(sql);
  assert.deepEqual([row.status, row.version, row.confirmed_at, JSON.parse(row.counts_json)[1].kept], ['pending_confirm', 2, null, 14]);
  const edit = sql.prepare('SELECT * FROM advisor_report_edits').get();
  assert.deepEqual([edit.report_id, edit.contact_id, edit.message_id], [row.id, 'c1', fix.m.id]);
  assert.deepEqual(JSON.parse(edit.patch_json).map(p => p.field), ['counts']);
  assert.equal(boatRow(sql).clean_reports, 0, 'reset on any edit before confirm');
  // Anything else: the model, whose brief carries the pending report and its id.
  const requests = [];
  const api = async (_url, init) => { requests.push(JSON.parse(init.body)); return new Response(JSON.stringify({content: [{type: 'text', text: 'Sure.'}], stop_reason: 'end_turn', usage: {}}), {status: 200}); };
  const other = await say(env, sql, 'how was the swell out there today?', {at: T0 + 2000, api});
  assert.equal(other.intent, 'chat');
  assert.match(requests[0].system[1].text, new RegExp(`- report waiting for confirmation: yes \\(report_id ${row.id}; Rita G, Sat Oct 3, 22 anglers: 45 vermilion, 14 lings\\)`));
  const no = await say(env, sql, 'no', {at: T0 + 3000});
  assert.deepEqual([no.intent, no.texts], ['report.withdraw', [t('en', 'report_withdrawn')]]);
  assert.equal(report(sql).status, 'withdrawn');
  assert.equal(pagesVersion(sql), null, 'a withdrawn draft was never public');
  // A confirm after a correction publishes, but is not a clean report.
  await say(env, sql, '20 anglers, 30 vermilion, 4 lings', {at: T0 + 4000});
  assert.deepEqual([report(sql).status, report(sql).version], ['pending_confirm', 3], 'the withdrawn report of the day comes back as pending (an edit, not a second row)');
  await say(env, sql, 'y', {at: T0 + 5000});
  assert.deepEqual([report(sql).status, boatRow(sql).clean_reports], ['published', 0]);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_reports').get().n, 1);
});

dbTest('the unique (boat, day, source): a second board or text the same day is an edit of the first, pending or published', async () => {
  const {sql, env} = setup();
  await say(env, sql, '22 anglers, 45 vermilion, 12 lings');
  const again = await say(env, sql, '22 anglers, 50 vermilion, 12 lings, 2 cabezon', {at: T0 + 1000});
  assert.equal(again.intent, 'report.text');
  assert.match(again.texts[0], /^Rita G, Sat Oct 3, 22 anglers:\n50 vermilion, 12 lings, 2 cabezon\nReply Y/);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_reports').get().n, 1);
  assert.deepEqual([report(sql).version, sql.prepare('SELECT COUNT(*) n FROM advisor_report_edits').get().n], [2, 1]);
  await say(env, sql, 'y', {at: T0 + 2000});
  // After publishing, a new text for the day updates the published report in place.
  const after = await say(env, sql, '22 anglers, 52 vermilion, 12 lings, 2 cabezon', {at: T0 + 3000});
  assert.match(after.texts[0], /^Got it, I've updated that day's posted report:\nRita G, Sat Oct 3, 22 anglers:\n52 vermilion/);
  assert.deepEqual([report(sql).status, report(sql).version, pagesVersion(sql)], ['published', 3, '2']);
  // A count board the same day as a typed report is an edit too (one live report per boat and day).
  const board = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mb1'});
  const b = await say(env, sql, null, {media: [board], at: T0 + 4000, vision: BOARD});
  assert.equal(b.intent, 'report.count_board');
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_reports').get().n, 1);
  assert.equal(report(sql).version, 4);
  // A different day is a new report ("yesterday ...").
  await say(env, sql, 'yesterday 15 anglers 70 rockfish 10 lings', {at: T0 + 5000});
  assert.deepEqual(sql.prepare('SELECT report_date FROM advisor_reports ORDER BY report_date').all().map(x => x.report_date), ['2026-10-02', TODAY]);
});

dbTest('the consumer turns a raced unique-constraint collision into an edit; a retried message makes no second row or edit', async () => {
  const {sql, db, env} = setup();
  const contact = {id: 'c1'};
  const base = {boat_id: 'b1', source: 'text', media_id: null, report_date: TODAY, trip_type: null, anglers: 22, notes: null, counts: [{species_key: 'lingcod', label: 'lings', kept: 12, released: null}]};
  assert.equal(await r.insertDraft(db, contact, 'mA', {...base, id: 'rA'}, false, T0, '0'), 'inserted');
  assert.equal(await r.insertDraft(db, contact, 'mA', {...base, id: 'rA'}, false, T0, '0'), 'retry');
  assert.equal(await r.insertDraft(db, contact, 'mB', {...base, id: 'rB', counts: [{species_key: 'lingcod', label: 'lings', kept: 14, released: null}]}, false, T0 + 1, '0'), 'edited');
  assert.equal(await r.insertDraft(db, contact, 'mB', {...base, id: 'rB'}, false, T0 + 1, '0'), 'edited');
  assert.deepEqual([sql.prepare('SELECT COUNT(*) n FROM advisor_reports').get().n, sql.prepare('SELECT COUNT(*) n FROM advisor_report_edits').get().n, report(sql).version], [1, 1, 2]);
  // Someone not on the boat cannot write its reports.
  addContact(sql, {id: 'c9', phone_hash: 'h9', phone_enc: 'E9', role: 'angler'});
  assert.equal(await r.insertDraft(db, {id: 'c9'}, 'mC', {...base, id: 'rC', report_date: '2026-10-02'}, false, T0, '0'), 'refused');
  assert.equal(await r.publishReport(db, {id: 'c9'}, 'rA', T0), false);
  assert.equal(await r.applyEdit(db, {id: 'c9'}, 'mD', '0', 'rA', {anglers: 1}, {}, T0), 'refused');
});

dbTest('clean_reports: + 1 per clean confirm, reset by an edit before confirm; the AUTO offer once at ADVISOR_AUTO_PUBLISH_AFTER', async () => {
  const {sql, env} = setup({env: {ADVISOR_AUTO_PUBLISH_AFTER: '2'}});
  // One trip a day, each confirmed with Y.
  const day = n => T0 + n * DAY;
  await say(env, sql, '22 anglers, 45 vermilion, 12 lings', {at: day(0)});
  const one = await say(env, sql, 'y', {at: day(0) + 1000});
  assert.deepEqual([boatRow(sql).clean_reports, one.texts.length], [1, 1]);
  await say(env, sql, '20 anglers, 30 vermilion, 6 lings', {at: day(1)});
  const two = await say(env, sql, 'y', {at: day(1) + 1000});
  assert.equal(boatRow(sql).clean_reports, 2);
  assert.deepEqual(two.texts, ['Posted. https://skippercast.com/boats/rita-g?s=txt', "You've had 2 clean reports. Want me to post your reports without asking? Reply AUTO."]);
  // Offered once: the next clean confirm does not repeat it.
  await say(env, sql, '18 anglers, 30 vermilion, 6 lings', {at: day(2)});
  const three = await say(env, sql, 'y', {at: day(2) + 1000});
  assert.deepEqual([boatRow(sql).clean_reports, three.texts.length], [3, 1]);
  // An edit before a confirm resets the count, and that confirm does not count.
  await say(env, sql, '18 anglers, 30 vermilion, 6 lings', {at: day(3)});
  await say(env, sql, 'lings were 7', {at: day(3) + 1000});
  assert.equal(boatRow(sql).clean_reports, 0);
  await say(env, sql, 'y', {at: day(3) + 2000});
  assert.equal(boatRow(sql).clean_reports, 0);
  // An edit after publishing leaves the count alone.
  await say(env, sql, '18 anglers, 30 vermilion, 6 lings', {at: day(4)});
  await say(env, sql, 'y', {at: day(4) + 1000});
  await say(env, sql, 'lings were 8', {at: day(4) + 2000});
  assert.equal(boatRow(sql).clean_reports, 1);
  // The setting at 0 never offers.
  const off = setup({env: {ADVISOR_AUTO_PUBLISH_AFTER: '0'}, boat: {clean: 9}});
  await say(off.env, off.sql, '22 anglers, 45 vermilion, 12 lings');
  assert.equal((await say(off.env, off.sql, 'y', {at: T0 + 1000})).texts.length, 1);
});

dbTest('AUTO turns auto-publish on (owner only); a report then posts at once with the one-line summary; ASK ME turns it off; default stays confirm-first', async () => {
  const {sql, env} = setup();
  addContact(sql, {id: 'crew1', phone_hash: 'hc', phone_enc: 'EC', role: 'crew', boat_id: 'b1'});
  sql.prepare("INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('b1','crew1','c1',?)").run(iso(T0));
  const crew = await say(env, sql, 'auto', {contact: 'crew1'});
  assert.deepEqual([crew.intent, boatRow(sql).auto_publish], ['report.auto.not_owner', 0]);
  const on = await say(env, sql, 'AUTO', {at: T0 + 1000});
  assert.deepEqual([on.intent, boatRow(sql).auto_publish, on.texts], ['report.auto.on', 1, [t('en', 'auto_on')]]);
  const posted = await say(env, sql, '22 anglers, 45 vermilion, 12 lings', {at: T0 + 2000});
  assert.deepEqual(posted.texts, ['Posted: Rita G, Sat Oct 3, 22 anglers: 45 vermilion, 12 lings. Text me any fix. https://skippercast.com/boats/rita-g?s=txt']);
  const row = report(sql);
  assert.deepEqual([row.status, row.confirmed_at, row.published_at], ['published', null, iso(T0 + 2000)], 'auto-published, not confirmed');
  assert.equal(boatRow(sql).clean_reports, 0, 'not a clean confirm');
  // A correction to it still works (05: "so corrections stay easy").
  const fix = await say(env, sql, 'lings were 14', {at: T0 + 3000});
  assert.deepEqual([fix.texts, report(sql).status, report(sql).version], [['Updated: 14 lings.'], 'published', 2]);
  // A board with an uncertain line still asks first.
  const board = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mb-unsure'});
  const unsure = {...BOARD, record_count_board: {...vfixture('count-board.json'), content: [{type: 'tool_use', id: 'u', name: 'record_count_board', input: {...vfixture('count-board.json').content[0].input,
    date_iso: '2026-10-02', date_confidence: 0.9, lines: [{label: 'Vermilion', count: 40, released: null, confidence: 0.6}]}}]}};
  const b = await say(env, sql, null, {media: [board], at: T0 + 4000, vision: unsure});
  assert.match(b.texts[0], /^Rita G, Fri Oct 2, 22 anglers:\n40\? vermilion\nReply Y to post/);
  assert.equal(report(sql, "report_date='2026-10-02'").status, 'pending_confirm');
  const off = await say(env, sql, 'ask me', {at: T0 + 5000});
  assert.deepEqual([off.intent, boatRow(sql).auto_publish], ['report.auto.off', 0]);
  await say(env, sql, 'y', {at: T0 + 6000});
  const next = await say(env, sql, '10 anglers, 20 vermilion, 2 lings', {at: T0 + DAY});
  assert.match(next.texts[0], /Reply Y to post/, 'confirm-first again');
});

// ---- corrections after publishing, the 7-day window, other contacts -----------------------------

dbTest('corrections apply to the boat\'s latest report of the last 7 days (published too); crew can correct; date moves are checked', async () => {
  const {sql, env} = setup();
  addContact(sql, {id: 'crew1', phone_hash: 'hc', phone_enc: 'EC', role: 'crew', boat_id: 'b1'});
  sql.prepare("INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('b1','crew1','c1',?)").run(iso(T0));
  await say(env, sql, '22 anglers, 45 vermilion, 12 lings');
  await say(env, sql, 'y', {at: T0 + 1000});
  const fix = await say(env, sql, 'lings were 14', {contact: 'crew1', at: T0 + 2000});
  assert.deepEqual([fix.intent, fix.texts], ['report.edit', ['Updated: 14 lings.']]);
  assert.deepEqual([report(sql).status, report(sql).version, pagesVersion(sql)], ['published', 2, '2'], 'a published edit bumps the pages version again');
  assert.equal(sql.prepare('SELECT contact_id FROM advisor_report_edits').get().contact_id, 'crew1');
  // Moving it onto a day that already has a report is refused.
  await say(env, sql, 'yesterday 10 anglers, 20 vermilion, 2 lings', {at: T0 + 3000});
  await say(env, sql, 'y', {at: T0 + 4000});
  const latest = report(sql);
  const move = await say(env, sql, 'it was today', {at: T0 + 5000});
  assert.deepEqual(move.texts, ["You already have a report for Sat Oct 3. Fix that one, or tell me the right date."]);
  assert.equal(report(sql, `id='${latest.id}'`).report_date, '2026-10-02');
  // Eight days later there is nothing to correct; the text goes to the model.
  const late = await quiet(() => runTurn({env: {...env, ANTHROPIC_API_KEY: undefined}, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: inbound(sql, 'lings were 15', {at: T0 + 9 * DAY}), now: T0 + 9 * DAY, deps: {}}));
  assert.equal(late.value.intent, 'unconfigured');
});

dbTest('anglers, web visitors and boatless contacts never reach the report flow', async () => {
  const {sql, env} = setup({contact: {role: 'angler', boat_id: null}});
  const res = await quiet(() => runTurn({env: {...env, ANTHROPIC_API_KEY: undefined}, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: inbound(sql, '22 anglers, 45 vermilion, 12 lings'), now: T0, deps: {}}));
  assert.equal(res.value.intent, 'unconfigured');
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_reports').get().n, 0);
  assert.deepEqual(STAGE_TWO_FLOWS.map(f => f.name), ['skipper', 'reports', 'anglers']);
});

// ---- the media path (05 § count board, § catch and action photos, § videos) ------------------------

dbTest('a count-board photo: classify -> read -> draft -> the confirmation; consent queues the board photo; a retried message re-reads nothing', async () => {
  const {sql, env} = setup({boat: {consent: iso(T0 - DAY), instagram: 'ritag'}});
  const id = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mb1'});
  const res = await say(env, sql, null, {media: [id], vision: BOARD});
  assert.deepEqual([res.intent, res.texts], ['report.count_board', [CONFIRM_TEXT]]);
  assert.deepEqual(res.visionCalls, ['record_classification', 'record_count_board']);
  const row = report(sql);
  assert.deepEqual([row.source, row.media_id, row.status], ['count-board', 'mb1', 'pending_confirm']);
  assert.deepEqual({...sql.prepare("SELECT publish_state,credit FROM advisor_media WHERE id='mb1'").get()}, {publish_state: 'queued', credit: 'Rita G'}, '05 step 5: Story material, with consent');
  const cached = JSON.parse(sql.prepare("SELECT classification_json FROM advisor_media WHERE id='mb1'").get().classification_json);
  assert.deepEqual(Object.keys(cached).sort(), ['classify', 'count_board']);
  // The same message again: the cached results, the same report.
  sql.prepare("UPDATE advisor_messages SET status='queued' WHERE id=?").run(res.m.id);
  const v = visionApi({});
  await quiet(() => consumeAdvisor(batchOf(res.m.id), env, {channelFor: () => recorder(), handler: engineHandler, now: () => T0, engine: {fetcher: v.fetcher, clock: () => T0}}));
  assert.deepEqual([v.calls, sql.prepare('SELECT COUNT(*) n FROM advisor_reports').get().n], [[], 1]);
});

dbTest('an unreadable board gets the 05 "couldn\'t read" text; vision down asks for the numbers; nothing is drafted', async () => {
  const {sql, env} = setup();
  const id = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mb2'});
  const low = {...BOARD, record_count_board: {...vfixture('count-board.json'), content: [{type: 'tool_use', id: 'l', name: 'record_count_board', input: {...vfixture('count-board.json').content[0].input, overall_confidence: 0.3}}]}};
  const res = await say(env, sql, null, {media: [id], vision: low});
  assert.deepEqual([res.intent, res.texts], ['report.board_unreadable', ["I couldn't read that one. Can you send a clearer shot, or just text me the numbers (e.g. '22 anglers, 45 vermilion, 12 lings')?",
    t('en', 'consent_ask', {name: 'Rita G'})]], 'no report waits for Y, so TA-I1\'s 7-day consent re-ask follows the photo reply');
  const id2 = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mb3'});
  const down = await say(env, sql, null, {media: [id2], vision: {}, at: T0 + 1000});
  assert.deepEqual([down.intent, down.texts[0]], ['media.unreadable', t('en', 'media_unavailable')]);
  assert.deepEqual(down.texts.slice(1), [t('en', 'consent_declined')], 'a photo instead of a YES: TA-I1\'s one-time decline line follows');
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_reports').get().n, 0);
});

dbTest('a catch photo with consent is queued and tagged; without consent the no-consent line once per 7 days; has_person opens a media review', async () => {
  // Consent and a handle: queued, tagged.
  const a = setup({boat: {consent: iso(T0 - DAY), instagram: 'ritag'}});
  const fish = addMedia(a.sql, a.env.ADVISOR_MEDIA, {id: 'mf1', bytes: png('fish.png')});
  const res = await say(a.env, a.sql, null, {media: [fish], vision: FISH});
  assert.deepEqual([res.intent, res.texts], ['media.photo', ["Nice. That's queued for the SkipperCast feed, tagged @ritag. Count board too?"]]);
  assert.equal(a.sql.prepare("SELECT publish_state FROM advisor_media WHERE id='mf1'").get().publish_state, 'queued');
  assert.equal(a.sql.prepare('SELECT COUNT(*) n FROM advisor_reviews').get().n, 0, 'no person: no review');
  // A person in it: queued and a has_person review (which texts the admin, 08).
  const person = addMedia(a.sql, a.env.ADVISOR_MEDIA, {id: 'mp1', bytes: png('deck-person.png')});
  const held = await say(a.env, a.sql, null, {media: [person], vision: PERSON});
  assert.deepEqual(held.texts, ["Nice. That's queued for the SkipperCast feed, tagged @ritag. Count board too?"]);
  assert.equal(a.sql.prepare("SELECT publish_state FROM advisor_media WHERE id='mp1'").get().publish_state, 'queued');
  assert.deepEqual({...a.sql.prepare('SELECT id,kind,ref_id,reason,status FROM advisor_reviews').get()}, {id: await reviewId('media', 'mp1', 'has_person'), kind: 'media', ref_id: 'mp1', reason: 'has_person', status: 'open'});
  // No consent: nothing queued, the line once, then a plain thanks.
  const b = setup();
  {
    const p1 = addMedia(b.sql, b.env.ADVISOR_MEDIA, {id: 'mn1', bytes: png('fish.png')});
    const first = await say(b.env, b.sql, null, {media: [p1], vision: FISH});
    assert.deepEqual(first.texts[0], t('en', 'photo_no_consent'));
    const p2 = addMedia(b.sql, b.env.ADVISOR_MEDIA, {id: 'mn2', bytes: png('fish.png')});
    const second = await say(b.env, b.sql, null, {media: [p2], vision: FISH, at: T0 + 1000});
    assert.equal(second.texts[0], t('en', 'photo_thanks'));
    assert.deepEqual(b.sql.prepare("SELECT publish_state FROM advisor_media WHERE id IN ('mn1','mn2')").all().map(x => x.publish_state), ['private', 'private']);
    // Seven days after the line it is said again (once per 7 days).
    const p3 = addMedia(b.sql, b.env.ADVISOR_MEDIA, {id: 'mn3', bytes: png('fish.png')});
    const week = await say(b.env, b.sql, null, {media: [p3], vision: FISH, at: T0 + 7 * DAY});
    assert.equal(week.texts[0], t('en', 'photo_no_consent'));
    const p4 = addMedia(b.sql, b.env.ADVISOR_MEDIA, {id: 'mn4', bytes: png('fish.png')});
    assert.equal((await say(b.env, b.sql, null, {media: [p4], vision: FISH, at: T0 + 7 * DAY + 1000})).texts[0], t('en', 'photo_thanks'));
  }
  // Consent but no handle: the owner is asked once; "@ritag" saves it; crew are never asked.
  const c = setup({boat: {consent: iso(T0 - DAY)}});
  const q1 = addMedia(c.sql, c.env.ADVISOR_MEDIA, {id: 'mh1', bytes: png('fish.png')});
  const ask = await say(c.env, c.sql, null, {media: [q1], vision: FISH});
  assert.deepEqual(ask.texts, [t('en', 'photo_queued_ask_handle')]);
  const q2 = addMedia(c.sql, c.env.ADVISOR_MEDIA, {id: 'mh2', bytes: png('fish.png')});
  assert.deepEqual((await say(c.env, c.sql, null, {media: [q2], vision: FISH, at: T0 + 1000})).texts, [t('en', 'photo_queued_untagged')], 'asked once');
  const handle = await say(c.env, c.sql, 'ritag_sportfishing', {at: T0 + 2000});
  assert.deepEqual([handle.intent, handle.texts], ['skipper.instagram', ['Thanks. I\'ll tag @ritag_sportfishing on your posts.']]);
  assert.equal(boatRow(c.sql).instagram, 'ritag_sportfishing');
});

dbTest('video: a Reel candidate with consent; a file the intake rejected (over 300 MB, unknown container) gets the upload link; MediaTooLarge gets the upload link and a log', async () => {
  const {sql, env} = setup({boat: {consent: iso(T0 - DAY), instagram: 'ritag'}});
  const vid = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mv1', kind: 'video', mime: 'video/mp4', bytes: Buffer.alloc(64)});
  const v = await say(env, sql, null, {media: [vid]});
  assert.deepEqual([v.intent, v.texts], ['media.video', ['Nice. That video is queued as a Reel for the SkipperCast feed, tagged @ritag.']]);
  assert.deepEqual([v.visionCalls, sql.prepare("SELECT publish_state FROM advisor_media WHERE id='mv1'").get().publish_state], [[], 'queued'], 'no vision call for a video');
  const bad = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mr1', kind: 'unknown', mime: 'application/octet-stream', bytes: Buffer.alloc(8), state: 'rejected'});
  const up = await say(env, sql, null, {media: [bad]});
  assert.equal(up.intent, 'media.upload_link');
  assert.match(up.texts[0], /^I couldn't take that file by text\. Send it through this link, good for 24 hours: https:\/\/skippercast\.com\/u\/[\w-]{20,}$/);
  const big = addMedia(sql, env.ADVISOR_MEDIA, {id: 'ml1', mime: 'image/jpeg', bytes: Buffer.alloc(5 * 1024 * 1024)});
  const large = await say(env, sql, null, {media: [big], vision: BOARD});
  assert.equal(large.intent, 'media.upload_link');
  assert.match(large.texts[0], /^That photo is too big for me to read by text\. Send it through this link/);
  assert.ok(large.lines.some(l => /advisor_media_too_large_wait_not_built/.test(l)), 'logged until TA-M1 builds the wait');
  assert.deepEqual(large.visionCalls, []);
});

dbTest('a crew member\'s board is the boat\'s report; consent is the boat\'s; the consent re-ask never shares a turn with "Reply Y"', async () => {
  const {sql, env} = setup();
  addContact(sql, {id: 'crew1', phone_hash: 'hc', phone_enc: 'EC', role: 'crew', boat_id: 'b1'});
  sql.prepare("INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('b1','crew1','c1',?)").run(iso(T0));
  const id = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mc1', contact: 'crew1'});
  const res = await say(env, sql, null, {contact: 'crew1', media: [id], vision: BOARD});
  assert.deepEqual(res.texts, [CONFIRM_TEXT]);
  assert.deepEqual([report(sql).boat_id, report(sql).contact_id], ['b1', 'crew1']);
  assert.equal(sql.prepare("SELECT publish_state FROM advisor_media WHERE id='mc1'").get().publish_state, 'private', 'no consent: the board stays private');
  // The owner's board after 7+ days without consent: the confirmation only, no consent question in the same turn.
  const own = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mo1'});
  const later = T0 + 8 * DAY;
  const o = await say(env, sql, null, {media: [own], vision: BOARD, at: later});
  assert.equal(o.texts.length, 1);
  assert.match(o.texts[0], /Reply Y to post/);
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM job_state WHERE key='advisor.flow.c1'").get().n, 0, 'the re-ask waits for the next photo');
});

// ---- the tools --------------------------------------------------------------------------------------

const toolCtx = (env, sql, over = {}) => ({env, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: {id: over.message ?? 'in-tool', created_at: iso(T0)},
  deps: over.deps ?? {}, db: env.DB, language: 'en', settings: advisorSettings(env), now: T0});

dbTest('propose_report: the model\'s structure becomes the same draft and confirmation; labels map to species here', async () => {
  const {sql, env} = setup();
  const out = await TOOL_BY_NAME.get('propose_report').run({anglers: 22, trip_type: 'Full Day', counts: [{label: 'reds', kept: 45, species_key: 'unicorn'}, {label: 'lings', kept: 12, released: 2}], notes: 'slow start'}, toolCtx(env, sql));
  assert.equal(out.result.proposed, true);
  assert.deepEqual(out.actions.map(a => a.type), ['report_draft', 'send_text']);
  assert.deepEqual(out.actions[0].report.counts, [{species_key: 'rockfish', label: 'reds', kept: 45, released: null}, {species_key: 'lingcod', label: 'lings', kept: 12, released: 2}], 'the model\'s species_key is not trusted');
  assert.equal(out.actions[1].text, 'Rita G, Sat Oct 3, full day, 22 anglers:\n45 reds, 12 lings (2 released)\nNotes: slow start\nReply Y to post, or tell me what to fix.');
  assert.deepEqual((await TOOL_BY_NAME.get('propose_report').run({report_date: '2026-09-01', counts: [{label: 'lings', kept: 1}]}, toolCtx(env, sql))).result.proposed, false);
  assert.equal((await TOOL_BY_NAME.get('propose_report').run({counts: []}, toolCtx(env, sql))).result.proposed, false);
});

dbTest('edit_report: a patch list (set, add, remove, fields) is the same report_edit; unknown ids and other boats are refused', async () => {
  const {sql, env} = setup();
  await say(env, sql, '22 anglers, 45 vermilion, 12 lings, 3 cabezon');
  const id = report(sql).id;
  const out = await TOOL_BY_NAME.get('edit_report').run({report_id: id, patch: [{label: 'vermilion', kept: 40}, {label: 'cabezon', remove: true}, {label: 'halibut', kept: 1}, {field: 'anglers', value: '20'}, {label: 'x'}]}, toolCtx(env, sql));
  assert.deepEqual([out.result.edited, out.result.rejected], [true, [4]]);
  assert.equal(out.actions[1].text, 'Updated: 40 vermilion, cabezon removed, 1 halibut, 20 anglers. Reply Y to post, or tell me what to fix.');
  // Applied through the consumer like any action.
  const m = inbound(sql, 'make the reds 40, drop the cabezon, add a hali, 20 people');
  await quiet(() => consumeAdvisor(batchOf(m.id), env, {channelFor: () => recorder(), handler: async () => ({actions: out.actions, intent: 'report.edit'}), now: () => T0}));
  const row = report(sql);
  assert.deepEqual([row.version, row.anglers, JSON.parse(row.counts_json).map(c => `${c.kept} ${c.label}`)], [2, 20, ['40 vermilion', '12 lings', '1 halibut']]);
  assert.equal((await TOOL_BY_NAME.get('edit_report').run({report_id: 'nope', patch: [{label: 'lings', kept: 1}]}, toolCtx(env, sql))).result.edited, false);
});

dbTest('read_count_board: reads a photo by id (with a caption the model saw) into the same draft; another contact\'s photo is refused', async () => {
  const {sql, env} = setup();
  const id = addMedia(sql, env.ADVISOR_MEDIA, {id: 'mb9'});
  const v = visionApi(BOARD);
  const out = await TOOL_BY_NAME.get('read_count_board').run({media_id: id}, toolCtx(env, sql, {deps: {fetcher: v.fetcher}}));
  assert.equal(out.result.read, true);
  assert.deepEqual(out.actions.map(a => a.type), ['report_draft', 'send_text']);
  assert.equal(out.actions[1].text, CONFIRM_TEXT);
  assert.deepEqual(v.calls, ['record_count_board'], 'the model asked for a board: no classify call');
  addContact(sql, {id: 'c2', phone_hash: 'h2', phone_enc: 'E2', role: 'angler'});
  addMedia(sql, env.ADVISOR_MEDIA, {id: 'other', contact: 'c2', boat: null});
  assert.equal((await TOOL_BY_NAME.get('read_count_board').run({media_id: 'other'}, toolCtx(env, sql))).result.read, false);
  // The engine shows a skipper's captioned photo to the model with its media id.
  const requests = [];
  const api = async (_url, init) => { requests.push(JSON.parse(init.body)); return new Response(JSON.stringify({content: [{type: 'text', text: 'ok'}], stop_reason: 'end_turn', usage: {}}), {status: 200}); };
  await say(env, sql, "here's today's board", {media: [id], api, at: T0 + 1000});
  assert.match(requests[0].messages.at(-1).content, /here's today's board \[photo, media_id mb9\]$/);
});

// ---- strings -----------------------------------------------------------------------------------------

test('every TA-I2 string has English and Spanish, and the 05 wording is exact', () => {
  const keys = ['report_confirm_ask', 'report_released', 'report_anglers', 'report_no_counts', 'report_notes', 'trip_half_day', 'trip_full_day', 'trip_overnight', 'report_posted',
    'report_withdrawn', 'report_updated', 'report_removed', 'report_replaced', 'report_date_taken', 'report_day_held', 'report_board_unreadable', 'report_auto_posted', 'auto_offer', 'auto_on',
    'auto_off', 'photo_queued', 'photo_queued_ask_handle', 'photo_queued_untagged', 'video_queued', 'video_queued_ask_handle', 'video_queued_untagged', 'photo_no_consent', 'photo_thanks',
    'video_thanks', 'media_use_upload', 'media_too_large', 'media_unavailable', 'media_what', 'media_received', 'instagram_saved'];
  for (const key of keys) {
    assert.ok(STRINGS[key], key);
    assert.ok(STRINGS[key].en.trim() && STRINGS[key].es.trim() && STRINGS[key].en !== STRINGS[key].es, key);
  }
  assert.equal(t('en', 'report_confirm_ask'), 'Reply Y to post, or tell me what to fix.');
  assert.equal(t('en', 'report_posted', {slug: 'rita-g'}), 'Posted. {{link:boat:rita-g}}');
  assert.equal(t('en', 'report_board_unreadable'), "I couldn't read that one. Can you send a clearer shot, or just text me the numbers (e.g. '22 anglers, 45 vermilion, 12 lings')?");
  assert.equal(t('en', 'photo_queued', {instagram: 'ritag'}), "Nice. That's queued for the SkipperCast feed, tagged @ritag. Count board too?");
  assert.equal(t('en', 'auto_offer', {n: 5}), "You've had 5 clean reports. Want me to post your reports without asking? Reply AUTO.");
  assert.equal(t('en', 'report_updated', {changes: '14 lingcod (2 released)'}), 'Updated: 14 lingcod (2 released).');
});
