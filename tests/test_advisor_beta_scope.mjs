// BF-advisor-beta: the Text Advisor pilot's scope (ADVISOR_BETA_REGIONS, ADVISOR_BETA_LANGS). Both optional and
// failing closed: unset, empty or all-invalid means no restriction (and health says so); set, an inbound outside the
// regions or languages gets no reply at all, as with the advisor off; removing the vars restores today's behaviour.
// Offline: real migrations in node:sqlite, a fake Messages API that must never be called for an outside inbound.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {runTurn} = await import('../server/advisor/engine.ts');
const {betaScope, advisorSettings} = await import('../server/advisor/settings.ts');
const {inBetaScope, gate, boatsGate, pagesGate} = await import('../server/advisor/gate.ts');
const {adminHealth} = await import('../server/advisor/admin/health.ts');
const {Hono} = await import('hono');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T17:00:00Z');
const iso = ms => new Date(ms).toISOString();
const ON = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_NUMBER: '+155****0199'};
const PILOT = {ADVISOR_BETA_REGIONS: 'morro-bay', ADVISOR_BETA_LANGS: 'en'};

// What main answers HELP and AYUDA with (captured on origin/main before this change; the same for every region).
const HELP = {
  en: {actions: [{type: 'send_text', text: 'SkipperCast here. Ask me about conditions, rules or recent catches, or send a fish photo for an ID. Msg & data rates may apply. Reply HELP for help, STOP to opt out.'},
    {type: 'send_text', text: 'SkipperCast: fishing conditions, rules, catch reports and fish IDs by text. Ask a question or send a photo. Text STOP to stop, FORGET ME to erase your data. Help and contact: skippercast.com'}], intent: 'help'},
  es: {actions: [{type: 'send_text', text: 'Aquí SkipperCast. Pregúntame por condiciones, reglas o capturas recientes, o mándame la foto de un pez para identificarlo. Pueden aplicarse tarifas de mensajes y datos. Responde AYUDA para ayuda, STOP para darte de baja.'},
    {type: 'send_text', text: 'SkipperCast: condiciones de pesca, reglas, reportes de capturas e identificación de peces por mensaje. Haz una pregunta o manda una foto. Escribe STOP para dejar de recibir mensajes, OLVÍDAME para borrar tus datos. Ayuda y contacto: skippercast.com'}], intent: 'help'},
};
const DARK = {actions: [], intent: 'out_of_scope'};

/** One turn for a contact (language, home port) sending `body`, on a fresh database; `earlier` messages already today. */
async function turn(vars, {language = 'en', port = null, body = 'HELP', earlier = 0} = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,status,home_port,last_seen_at,created_at,updated_at) VALUES('c1','h1','ENC','imessage','angler',?,'active',?,?,?,?)`)
    .run(language, port, iso(T0), iso(T0), iso(T0));
  const add = (id, text, ago, status) => sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES(?,'c1','in','imessage',?,?,?,?)`).run(id, `p-${id}`, text, status, iso(T0 - ago * 60000));
  for (let i = 0; i < earlier; i++) add(`e${i}`, `earlier ${i}`, 10 + i, 'done');
  add('m1', body, 0, 'processing');
  const requests = [], fetcher = async (...a) => { requests.push(a); throw Error('no model call expected'); };
  const result = await runTurn({env: {...ON, DB: db, ...vars}, contact: sql.prepare('SELECT * FROM advisor_contacts').get(), message: sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get('m1'),
    now: T0, deps: {sleep: async () => {}, clock: () => T0, fetcher}});
  return {result, requests};
}

test('settings: lists are validated, deduplicated and fail closed to no restriction, with the dropped count', () => {
  const none = {regions: null, langs: null, dropped: {regions: 0, langs: 0}, ignored: {regions: false, langs: false}};
  for (const env of [{}, {ADVISOR_BETA_REGIONS: '', ADVISOR_BETA_LANGS: ''}, {ADVISOR_BETA_REGIONS: '  ', ADVISOR_BETA_LANGS: ' \t '}, {ADVISOR_BETA_REGIONS: ',,', ADVISOR_BETA_LANGS: ' , '}, undefined])
    assert.deepEqual(betaScope(env), none, JSON.stringify(env));
  assert.deepEqual(betaScope({ADVISOR_BETA_REGIONS: ' Morro-Bay , port-san-luis,morro-bay', ADVISOR_BETA_LANGS: 'EN, es'}),
    {regions: ['morro-bay', 'port-san-luis'], langs: ['en', 'es'], dropped: {regions: 0, langs: 0}, ignored: {regions: false, langs: false}});
  // junk: only-invalid lists are ignored and flagged; a mixed list keeps its valid entries and counts the rest
  assert.deepEqual(betaScope({ADVISOR_BETA_REGIONS: 'Morro Bay!,-bad,../x', ADVISOR_BETA_LANGS: 'fr,klingon'}),
    {regions: null, langs: null, dropped: {regions: 3, langs: 2}, ignored: {regions: true, langs: true}});
  assert.deepEqual(betaScope({ADVISOR_BETA_REGIONS: 'morro-bay,not a slug', ADVISOR_BETA_LANGS: 'en,fr'}),
    {regions: ['morro-bay'], langs: ['en'], dropped: {regions: 1, langs: 1}, ignored: {regions: false, langs: false}});
  assert.deepEqual(betaScope({ADVISOR_BETA_REGIONS: 5, ADVISOR_BETA_LANGS: {}}), none, 'a non-string var is unset');
  // the existing settings are untouched by the new vars
  assert.deepEqual(advisorSettings({...PILOT}), advisorSettings({}));
});

test('inBetaScope: no list is everyone; a region list refuses an unresolved region; a language list refuses the others', () => {
  const scope = (regions, langs) => ({regions, langs, dropped: {regions: 0, langs: 0}, ignored: {regions: false, langs: false}});
  assert.equal(inBetaScope(scope(null, null), null, 'es'), true, 'unrestricted serves an unresolved region');
  assert.equal(inBetaScope(scope(['morro-bay'], ['en']), 'morro-bay', 'en'), true);
  assert.equal(inBetaScope(scope(['morro-bay'], ['en']), 'monterey-point-sur', 'en'), false);
  assert.equal(inBetaScope(scope(['morro-bay'], ['en']), 'morro-bay', 'es'), false);
  assert.equal(inBetaScope(scope(['morro-bay'], null), null, 'en'), false, 'fail closed: region unresolved');
  assert.equal(inBetaScope(scope(null, ['en']), null, 'en'), true, 'a language-only pilot does not need a region');
  assert.equal(inBetaScope(scope(['morro-bay', 'port-san-luis'], null), 'port-san-luis', 'es'), true);
});

dbTest('pilot on: Morro Bay in English is served; another region, Spanish or an unresolved region gets nothing and no model call', async () => {
  assert.deepEqual((await turn(PILOT)).result, HELP.en, 'no home port: ADVISOR_REGION_DEFAULT is morro-bay');
  assert.deepEqual((await turn(PILOT, {port: 'morro-bay'})).result, HELP.en);
  for (const c of [{port: 'monterey'}, {language: 'es', port: 'morro-bay', body: 'ayuda'}, {language: 'es', body: 'HELP'}, {port: 'no-such-port'}]) {
    const {result, requests} = await turn(PILOT, c);
    assert.deepEqual(result, DARK, JSON.stringify(c));
    assert.equal(requests.length, 0, 'no model call');
  }
  // a Spanish message from a contact whose stored language is English is outside the English pilot, and needs no model
  const spanish = await turn(PILOT, {port: 'morro-bay', body: 'qué pica hoy en la bahía'});
  assert.deepEqual([spanish.result, spanish.requests.length], [DARK, 0]);
  // a Spanish-only pilot serves the Spanish command and refuses the English one
  const es = {ADVISOR_BETA_REGIONS: 'morro-bay', ADVISOR_BETA_LANGS: 'es'};
  assert.deepEqual((await turn(es, {language: 'es', body: 'ayuda'})).result, HELP.es);
  assert.deepEqual((await turn(es, {})).result, DARK);
  // a region list alone does not restrict language, and a language list alone does not restrict region
  assert.deepEqual((await turn({ADVISOR_BETA_REGIONS: 'morro-bay'}, {language: 'es', body: 'ayuda'})).result, HELP.es);
  assert.deepEqual((await turn({ADVISOR_BETA_LANGS: 'en'}, {port: 'monterey'})).result, HELP.en);
});

dbTest('both vars unset, empty, blank or junk: every inbound behaves exactly as on main, and rolling back restores it', async () => {
  const cases = [{}, {port: 'morro-bay'}, {port: 'monterey'}, {port: 'no-such-port'}, {language: 'es', port: 'morro-bay', body: 'ayuda'}, {language: 'es', body: 'ayuda'}];
  const unrestricted = [{}, {ADVISOR_BETA_REGIONS: '', ADVISOR_BETA_LANGS: ''}, {ADVISOR_BETA_REGIONS: '  ', ADVISOR_BETA_LANGS: '\t'},
    {ADVISOR_BETA_REGIONS: '!!,??', ADVISOR_BETA_LANGS: 'fr,xx'}];
  for (const vars of unrestricted) for (const c of cases)
    assert.deepEqual((await turn(vars, c)).result, HELP[c.language ?? 'en'], `${JSON.stringify(vars)} ${JSON.stringify(c)}`);
  // rollback: the same inputs with the pilot vars removed answer what they answered before the pilot was set
  for (const c of cases) {
    const during = (await turn(PILOT, c)).result, after = (await turn({}, c)).result;
    assert.deepEqual(after, HELP[c.language ?? 'en']);
    assert.deepEqual(during, (c.language ?? 'en') === 'en' && (c.port ?? 'morro-bay') === 'morro-bay' ? HELP.en : DARK, `during the pilot ${JSON.stringify(c)}`);
  }
});

dbTest('the existing caps still apply inside the scope; outside it the cap text is not sent either', async () => {
  const caps = {...PILOT, ADVISOR_DAILY_MESSAGES_PER_CONTACT: '3'};
  const inside = (await turn(caps, {port: 'morro-bay', body: 'one more', earlier: 3})).result;
  assert.equal(inside.intent, 'capped');
  assert.equal(inside.actions.length, 1);
  assert.deepEqual((await turn(caps, {port: 'monterey', body: 'one more', earlier: 3})).result, DARK);
  assert.equal((await turn(caps, {port: 'morro-bay', body: 'HELP', earlier: 3})).result.intent, 'help', 'HELP still works past the cap');
});

dbTest('admin health reports both lists, what was dropped, and an ignored (all-invalid) list', async () => {
  const health = async vars => (await adminHealth({...ON, DB: advisorDatabase().db, ...vars}, T0)).beta;
  assert.deepEqual(await health({}), {regions: null, langs: null, dropped: {regions: 0, langs: 0}, ignored: {regions: false, langs: false}});
  assert.deepEqual(await health(PILOT), {regions: ['morro-bay'], langs: ['en'], dropped: {regions: 0, langs: 0}, ignored: {regions: false, langs: false}});
  assert.deepEqual(await health({ADVISOR_BETA_REGIONS: 'morro-bay,Bad Id', ADVISOR_BETA_LANGS: 'fr'}),
    {regions: ['morro-bay'], langs: null, dropped: {regions: 1, langs: 1}, ignored: {regions: false, langs: true}});
  assert.deepEqual((await health({ADVISOR_BETA_REGIONS: '!!'})).ignored, {regions: true, langs: false});
});

test('boatsGate, pagesGate and gate: the advisor flag alone decides, with the pilot vars set or not', async () => {
  const app = new Hono();
  app.use('/api/*', gate); app.use('/boats/*', boatsGate); app.use('/ports/*', pagesGate);
  for (const p of ['/api/x', '/boats/x', '/ports/x']) app.get(p, c => c.text('ok'));
  const status = async (path, env) => (await app.fetch(new Request('https://skippercast.com' + path), env)).status;
  for (const vars of [{}, PILOT, {ADVISOR_BETA_REGIONS: '!!'}]) {
    assert.deepEqual([await status('/api/x', vars), await status('/boats/x', vars), await status('/ports/x', vars)], [404, 404, 404], 'dark');
    assert.deepEqual([await status('/boats/x', {...vars, FLEET_ENABLED: 'true'}), await status('/ports/x', {...vars, PUBLIC_PAGES_ENABLED: 'true'})], [200, 200], 'fleet and public pages on, advisor off');
    assert.deepEqual([await status('/api/x', {...vars, FLEET_ENABLED: 'true', PUBLIC_PAGES_ENABLED: 'true'})], [404], 'the advisor routes stay dark');
    assert.deepEqual([await status('/api/x', {...vars, ...ON}), await status('/boats/x', {...vars, ...ON}), await status('/ports/x', {...vars, ...ON})], [200, 200, 200], 'advisor on');
  }
});
