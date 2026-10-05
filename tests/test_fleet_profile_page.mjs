// Charter fleet public profile on /boats/<slug> (CF-33; docs/plans/charter-fleet/design.md
// § 13, § 17). Offline: the real migrations in node:sqlite, synthetic vessels, example.com
// URLs and 555-01XX phones only.
//
// Acceptance 1 is a snapshot: tests/fixtures/boat-page-snapshots/*.html are the advisor
// boat pages rendered by the code on main before CF-33 (commit "Snapshot advisor boat pages
// before CF-33"). With FLEET_ENABLED off (and with it on for a boat with no registry link)
// the page must stay byte-identical. They live outside tests/fixtures/fleet/ because the
// privacy scan there reads the JSON-LD keys ("@context", "@type") as Instagram mentions.
// Regenerate only for an intended advisor page change:
//   SNAPSHOT_WRITE=1 node --test tests/test_fleet_profile_page.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = '0123456789';
globalThis.ADVISOR_ASSETS = {'advisor/pages.css': '/assets/chat.abcdef0123.css', 'advisor/chat.js': '/assets/chat.0123abcdef.js'};
const {default: worker} = await import('../server/index.ts');
const {pagesDeps} = await import('../server/routes/advisor.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const NOW = Date.parse('2026-09-28T19:00:00Z');
const iso = ms => new Date(ms).toISOString();
const DAY = 86400000;
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ADVISOR = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_NUMBER: '+18055550123'};
const FLEET = {FLEET_ENABLED: 'true'};
pagesDeps.clock = () => NOW;
pagesDeps.feeds = async url => { throw Error(`no feed in this test: ${url}`); };
delete globalThis.caches;

function seedAdvisor(sql) {
  const at = iso(NOW - DAY);
  const boat = (id, slug, name, status, extra = {}) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,instagram,booking_url,phone_public,status,verified_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, slug, name, extra.landing ?? 'Gull\'s Landing', 'morro-bay', 'morro-bay', extra.instagram ?? null,
    extra.booking ?? null, extra.phone ?? null, status, status === 'verified' ? at : null, at, at);
  boat('b-sea', 'sea-example', 'Sea Example', 'verified', {instagram: 'seaexample_fishing', booking: 'https://example.com/book', phone: '+18055550188'});
  boat('b-gray', 'gray-example', 'Gray Example', 'pending');
  const report = (id, boatId, date, counts, verified, version = 1) => sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,published_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, boatId, 'morro-bay', 'morro-bay', date, 'full-day', 22, JSON.stringify(counts), 'count-text', 'published', verified, version, at, at, at);
  report('r1', 'b-sea', '2026-09-27', [{label: 'vermilion', species_key: 'rockfish', kept: 45, released: null}, {label: 'lingcod', species_key: 'lingcod', kept: 12, released: 2}], 1, 2);
  report('r2', 'b-sea', '2026-09-20', [{label: 'lingcod', species_key: 'lingcod', kept: 8, released: null}], 1);
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,credit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run('m-ok', 'c1', 'b-sea', 'image', 'image/jpeg', 100, 'advisor/media/c1/m-ok.jpg', 'x', 1, 'approved', 'Sea Example', at);
}

const get = (path, env, headers = {}) => worker.fetch(new Request(ORIGIN + path, {headers}), {ASSETS, ...env});

// ---- Acceptance 1: advisor boat pages are byte-identical with FLEET_ENABLED off ----------
const SNAPSHOTS = [
  ['sea-example.en.html', '/boats/sea-example'],
  ['sea-example.es.html', '/boats/sea-example?lang=es'],
  ['gray-example.en.html', '/boats/gray-example'],
];
const snapshotUrl = name => new URL(`./fixtures/boat-page-snapshots/${name}`, import.meta.url);

dbTest('acceptance 1: with FLEET_ENABLED off an advisor boat page is byte-identical to the pre-fleet snapshot', async () => {
  const {sql, db} = advisorDatabase(); seedAdvisor(sql);
  try {
    if (process.env.SNAPSHOT_WRITE === '1') {
      mkdirSync(new URL('./fixtures/boat-page-snapshots/', import.meta.url), {recursive: true});
      for (const [name, path] of SNAPSHOTS) writeFileSync(snapshotUrl(name), await (await get(path, {...ADVISOR, DB: db})).text());
    }
    for (const [name, path] of SNAPSHOTS) {
      const expected = readFileSync(snapshotUrl(name), 'utf8');
      for (const env of [{...ADVISOR}, {...ADVISOR, FLEET_ENABLED: 'false'}, {...ADVISOR, FLEET_ENABLED: 'yes'}]) {
        const response = await get(path, {...env, DB: db});
        assert.equal(response.status, 200, path);
        assert.equal(await response.text(), expected, `${path} with ${JSON.stringify(env.FLEET_ENABLED)}`);
      }
    }
  } finally { sql.close(); }
});
