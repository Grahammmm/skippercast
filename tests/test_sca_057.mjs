import test from 'node:test';
import assert from 'node:assert/strict';
import region from '../regions/morro-bay/region.json' with {type: 'json'};
import {advisorDatabase} from './_advisor_d1.mjs';

const port = 'morro-bay', date = '2026-09-28';
const now = Date.parse(`${date}T17:00:00Z`);
const base = 'https://example.invalid', link = `${base}/ports/${port}?s=txt`;
const zone = region.marine_zones.coastal;
const regionFixture = {...region, daily_feed: `${base}/latest.json`, intelligence_feed: `${base}/intelligence.json`};
Object.assign(globalThis, {REGIONS: {[port]: regionFixture}, DEPLOYMENT: {allowed_origins: []}, ADVISOR_ASSETS: {}});
const {dailyFlow, currentInputsHash} = await import('../server/advisor/answers/reports.ts');
const {portPage} = await import('../server/advisor/pages/port.ts');

const times = Array.from({length: 9}, (_, i) => (Date.parse(`${date}T13:00:00Z`) / 1000) + 3600 * i);
const forecast = {region_id: port, forecast: {models: {
  gfs_global: {meta: {last_run_initialisation_time: times[0]}, data: [{hourly: {time: times, wind_speed_10m: times.map(() => 6)}, hourly_units: {wind_speed_10m: 'kn'}}]},
}}};
function daily(alerts) {
  return {schema_version: 1, generated_at: new Date(now).toISOString(), region_id: port, health: {}, reports: [],
    catch_probability: null, bite_score: null, sources: Object.fromEntries(Object.values(region.marine_zones).map(id =>
      [`alerts-${id}`, {status: 'ok', checked_at: new Date(now).toISOString(), data: {alerts: id === zone ? alerts : []}}]))};
}
const gale = {event: 'Gale Warning', onset: `${date}T15:00:00Z`, ends: `${date}T20:00:00Z`};
const cached = {en: 'Comfortable on the water. Full picture:', es: 'Mar cómodo. Todo el detalle:'};
const warning = {en: /^GALE WARNING posted for today\./, es: /^GALE WARNING \(aviso del NWS\) para hoy\./};

for (const mode of ['current', 'warning with forecast down', 'alerts down', 'inapplicable warning']) {
  test(`SMS selection and port lead: ${mode}`, async (t) => {
    const {sql, db} = advisorDatabase();
    t.after(() => sql.close());
    const unexpected = [];
    const rejectModel = async (url) => { unexpected.push(String(url)); throw Error('External requests forbidden in SCA-057'); };
    t.mock.method(globalThis, 'fetch', rejectModel);
    const env = {DB: db, ADVISOR_PUBLIC_BASE: base, ANTHROPIC_API_KEY: 'synthetic-not-a-key'};
    const inputs = (alerts, down) => ({clock: () => now, fetcher: rejectModel, feeds: async url => {
      if (url === down) throw Error('Synthetic outage');
      if (url === regionFixture.daily_feed) return daily(alerts);
      if (url === regionFixture.intelligence_feed) return forecast;
      return rejectModel(url);
    }});
    const full = inputs([], null);
    const hash = await currentInputsHash(env, port, date, full, now);
    sql.prepare('INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES(?,?,?,?,?)')
      .run(`${port}:${date}`, `${cached.en} ${link}`, `${cached.es} ${link}`, hash, new Date(now - 3600000).toISOString());
    const answerRow = () => sql.prepare('SELECT * FROM advisor_daily_answers').get();
    const before = answerRow();
    const deps = mode === 'current' ? full : mode === 'alerts down' ? inputs([], regionFixture.daily_feed) :
      inputs([mode === 'inapplicable warning' ? {...gale, onset: `${date}T23:00:00Z`, ends: `${date}T23:30:00Z`} : gale], regionFixture.intelligence_feed);
    for (const language of ['en', 'es']) {
      const sms = await dailyFlow({env, db, now, deps, language, media: [], contact: {home_port: port},
        text: language === 'en' ? "What's biting in Morro Bay" : 'Qué está picando en Morro Bay'});
      const page = await portPage(env, port, language, {publicBase: base, number: null}, deps);
      const lead = page?.match(/<h2 id="today-title">[^<]*<\/h2>\s*<p>([^<]*)<\/p>/)?.[1];
      assert.ok(lead, 'public port lead is present');
      assert.equal(sms.actions[0].type, 'send_text'); // Action selected, not dispatched.
      if (mode === 'current') {
        assert.equal(sms.intent, 'reports.daily.cache');
        assert.equal(sms.actions[0].text, `${cached[language]} ${link}`);
        assert.equal(lead, cached[language].split('. ')[0] + '.');
      } else {
        for (const text of [sms.actions[0].text, lead]) {
          if (mode === 'warning with forecast down') assert.match(text, warning[language]);
          else assert.doesNotMatch(text, /gale warning/i);
          assert.doesNotMatch(text, /comfortable|mar cómodo/i);
        }
        assert.equal(sms.intent, 'reports.daily.composed');
      }
    }
    assert.deepEqual(answerRow(), before, 'preserve both languages, hash and timestamp for recovery');
    assert.deepEqual(unexpected, [], 'no public page or degraded SMS may request a model');
  });
}
