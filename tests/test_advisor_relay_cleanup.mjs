// The relay Mac's weekly cleanup (scripts/advisor/relay-cleanup.sh;
// docs/operations/runbooks/advisor-relay-setup.md § 12, threat model § 9.2):
// BlueBubbles' own attachment copies older than 7 days go; Messages' own
// attachments, chat.db and BlueBubbles' settings are never touched; --dry-run
// deletes nothing; --plist prints a weekly launchd agent. Runs the script
// against a throwaway HOME (bash and find, no macOS needed).
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, writeFileSync, existsSync, utimesSync, rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';

const SCRIPT = fileURLToPath(new URL('../scripts/advisor/relay-cleanup.sh', import.meta.url));
const DAY = 86400;
const bash = spawnSync('bash', ['--version']).status === 0;

function home() {
  const dir = mkdtempSync(join(tmpdir(), 'relay-cleanup-'));
  const now = Date.now() / 1000;
  const file = (rel, ageDays) => {
    const path = join(dir, rel);
    mkdirSync(join(path, '..'), {recursive: true});
    writeFileSync(path, 'x');
    utimesSync(path, now - ageDays * DAY, now - ageDays * DAY);
    return path;
  };
  const bb = 'Library/Application Support/bluebubbles-server';
  const files = {
    oldCached: file(`${bb}/Attachments/Cached/guid-1/IMG 0001.HEIC`, 10),
    oldOutgoing: file(`${bb}/Attachments/guid-2/board.jpg`, 8),
    oldConvert: file(`${bb}/Convert/guid-3/board.jpeg`, 30),
    oldMessagesCopy: file('Library/Messages/Attachments/BlueBubbles/guid-4/clip.mov', 9),
    newCached: file(`${bb}/Attachments/Cached/guid-5/today.jpg`, 1),
    sixDays: file(`${bb}/Convert/guid-6/recent.jpeg`, 6),
    messagesOwn: file('Library/Messages/Attachments/ab/01/at_0_X/IMG_0002.HEIC', 100),
    chatDb: file('Library/Messages/chat.db', 100),
    settings: file(`${bb}/config.db`, 100),
    certs: file(`${bb}/Certs/server.pem`, 100),
  };
  return {dir, files};
}
const run = (dir, args = [], env = {}) => spawnSync('bash', [SCRIPT, ...args], {encoding: 'utf8', env: {PATH: process.env.PATH, HOME: dir, ...env}});

test('relay cleanup deletes only BlueBubbles attachment copies older than 7 days', {skip: !bash && 'bash is not available'}, () => {
  const {dir, files} = home();
  try {
    const out = run(dir);
    assert.equal(out.status, 0, out.stderr);
    for (const key of ['oldCached', 'oldOutgoing', 'oldConvert', 'oldMessagesCopy']) assert.ok(!existsSync(files[key]), `${key} deleted`);
    for (const key of ['newCached', 'sixDays', 'messagesOwn', 'chatDb', 'settings', 'certs']) assert.ok(existsSync(files[key]), `${key} kept`);
    assert.match(out.stdout, /relay cleanup: 4 file\(s\) deleted/);
    assert.ok(!existsSync(join(dir, 'Library/Application Support/bluebubbles-server/Attachments/guid-2')), 'emptied folders go too');
    assert.ok(existsSync(join(dir, 'Library/Application Support/bluebubbles-server/Attachments/Cached/guid-5')));
    assert.match(run(dir).stdout, /relay cleanup: 0 file\(s\) deleted/, 'a second run finds nothing');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('relay cleanup --dry-run lists and keeps; RELAY_CLEANUP_DAYS changes the age; bad input is refused', {skip: !bash && 'bash is not available'}, () => {
  const {dir, files} = home();
  try {
    const dry = run(dir, ['--dry-run']);
    assert.equal(dry.status, 0, dry.stderr);
    assert.match(dry.stdout, /4 file\(s\) would be deleted/);
    assert.match(dry.stdout, /IMG 0001\.HEIC/, 'names with spaces are listed whole');
    for (const path of Object.values(files)) assert.ok(existsSync(path), path);
    assert.match(run(dir, ['--dry-run'], {RELAY_CLEANUP_DAYS: '20'}).stdout, /1 file\(s\) would be deleted/);
    assert.equal(run(dir, [], {RELAY_CLEANUP_DAYS: '7; rm -rf /'}).status, 2);
    assert.equal(run(dir, ['--force']).status, 2);
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('relay cleanup --plist prints a weekly launchd agent that runs this script', {skip: !bash && 'bash is not available'}, () => {
  const out = run('/Users/relay', ['--plist']);
  assert.equal(out.status, 0, out.stderr);
  assert.match(out.stdout, /<key>Label<\/key><string>com\.skippercast\.relay-cleanup<\/string>/);
  assert.match(out.stdout, /<string>\/bin\/bash<\/string><string>\/.+\/scripts\/advisor\/relay-cleanup\.sh<\/string>/);
  assert.match(out.stdout, /<key>Weekday<\/key><integer>0<\/integer><key>Hour<\/key><integer>4<\/integer>/);
  assert.match(out.stdout, /\/Users\/relay\/Library\/Logs\/com\.skippercast\.relay-cleanup\.log/);
});
