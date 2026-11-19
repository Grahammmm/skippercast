// The relay Mac's weekly cleanup (scripts/advisor/relay-cleanup.sh;
// docs/operations/runbooks/advisor-relay-setup.md § 12, threat model § 9.2):
// BlueBubbles' own attachment copies older than 7 days go; Messages' own
// attachments, chat.db and BlueBubbles' settings are never touched; --dry-run
// deletes nothing; --plist prints a weekly launchd agent. Runs the script
// against a throwaway HOME (bash and find, no macOS needed).
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {chmodSync, mkdtempSync, mkdirSync, writeFileSync, existsSync, utimesSync, rmSync} from 'node:fs';
import {dirname, join, relative} from 'node:path';
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
    oldCached: file(`${bb}/Attachments/Cached/guid-1/private draft\nscan.HEIC`, 10),
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

function assertNoPaths(out, dir, ...paths) {
  for (const stream of [out.stdout, out.stderr]) {
    assert.ok(!stream.includes(dir), 'synthetic HOME must not reach either log stream');
    for (const path of paths) {
      for (const component of relative(dir, path).split('/').slice(-2)) {
        for (const fragment of component.split('\n')) {
          assert.ok(!stream.includes(fragment), 'attachment name or subdirectory reached a log stream');
        }
      }
    }
  }
}

test('relay cleanup deletes only BlueBubbles attachment copies older than 7 days', {skip: !bash && 'bash is not available'}, () => {
  const {dir, files} = home();
  try {
    const out = run(dir);
    assert.equal(out.status, 0, out.stderr);
    assertNoPaths(out, dir, files.oldCached, files.oldOutgoing, files.oldConvert, files.oldMessagesCopy);
    for (const key of ['oldCached', 'oldOutgoing', 'oldConvert', 'oldMessagesCopy']) assert.ok(!existsSync(files[key]), `${key} deleted`);
    for (const key of ['newCached', 'sixDays', 'messagesOwn', 'chatDb', 'settings', 'certs']) assert.ok(existsSync(files[key]), `${key} kept`);
    assert.match(out.stdout, /relay cleanup: 4 file\(s\) deleted/);
    assert.ok(!existsSync(join(dir, 'Library/Application Support/bluebubbles-server/Attachments/guid-2')), 'emptied folders go too');
    assert.ok(existsSync(join(dir, 'Library/Application Support/bluebubbles-server/Attachments/Cached/guid-5')));
    rmSync(dirname(dirname(files.oldMessagesCopy)), {recursive: true});
    const second = run(dir);
    assert.equal(second.status, 0, 'an absent optional root is not a scan failure');
    assert.match(second.stdout, /relay cleanup: 0 file\(s\) deleted/, 'a second run finds nothing');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('relay cleanup --dry-run counts by role without paths and keeps files; age is configurable', {skip: !bash && 'bash is not available'}, () => {
  const {dir, files} = home();
  try {
    const dry = run(dir, ['--dry-run']);
    assert.equal(dry.status, 0, dry.stderr);
    assert.match(dry.stdout, /4 file\(s\) would be deleted/);
    assertNoPaths(dry, dir, files.oldCached, files.oldOutgoing, files.oldConvert, files.oldMessagesCopy);
    for (const [role, count] of [['attachments', 2], ['convert', 1], ['messages-copies', 1]]) {
      assert.ok(dry.stdout.includes(`${role}: ${count} file(s) would be deleted`));
    }
    for (const path of Object.values(files)) assert.ok(existsSync(path), path);
    assert.match(run(dir, ['--dry-run'], {RELAY_CLEANUP_DAYS: '20'}).stdout, /1 file\(s\) would be deleted/);
    assert.equal(run(dir, [], {RELAY_CLEANUP_DAYS: '7; rm -rf /'}).status, 2);
    assert.equal(run(dir, ['--force']).status, 2);
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

const permissionSkip = !bash ? 'bash is not available' : process.getuid?.() === 0 && 'root can bypass fixture permissions';

// A real find error must not leak its pathname or be lost behind an ordinary total.
test('relay cleanup reports an unreadable subtree as partial and still handles other roles', {skip: permissionSkip}, () => {
  const {dir, files} = home();
  const denied = dirname(files.oldCached);
  const messagesParent = dirname(dirname(dirname(files.oldMessagesCopy)));
  try {
    chmodSync(denied, 0o000);
    const dry = run(dir, ['--dry-run']);
    assert.equal(dry.status, 1, 'an incomplete scan must return nonzero');
    assert.match(dry.stderr, /attachments: scan or file removal incomplete/);
    assert.match(dry.stdout, /attachments: 1 file\(s\) would be deleted/);
    assert.match(dry.stdout, /convert: 1 file\(s\) would be deleted/);
    assert.match(dry.stdout, /relay cleanup: 3 file\(s\) would be deleted \(partial\)/);
    assertNoPaths(dry, dir, files.oldCached, files.oldOutgoing, files.oldConvert, files.oldMessagesCopy);
    assert.ok(existsSync(files.oldOutgoing), 'a partial dry run still deletes nothing');

    chmodSync(denied, 0o700);
    chmodSync(messagesParent, 0o000);
    const hiddenRoot = run(dir, ['--dry-run']);
    assert.equal(hiddenRoot.status, 1, 'a root behind a denied ancestor is not absent');
    assert.match(hiddenRoot.stderr, /messages-copies: scan or file removal incomplete/);
    assert.match(hiddenRoot.stdout, /messages-copies: 0 file\(s\) would be deleted \(partial\)/);
    assertNoPaths(hiddenRoot, dir, files.oldCached, files.oldMessagesCopy);
  } finally {
    chmodSync(denied, 0o700);
    chmodSync(messagesParent, 0o700);
    rmSync(dir, {recursive: true, force: true});
  }
});

// rm and the empty-directory prune also emit path-bearing diagnostics by default.
test('relay cleanup reports failed removals without logging their paths or counting them as done', {skip: permissionSkip}, () => {
  const {dir, files} = home();
  const unwritable = dirname(files.oldCached);
  const pruneParent = join(dirname(files.oldConvert), '..', 'private-prune-parent');
  const empty = join(pruneParent, 'private-empty-copy');
  try {
    mkdirSync(empty, {recursive: true});
    chmodSync(unwritable, 0o555);
    chmodSync(pruneParent, 0o555);
    const out = run(dir);
    assert.equal(out.status, 1);
    assert.match(out.stderr, /attachments: scan or file removal incomplete/);
    assert.match(out.stderr, /convert: empty-directory removal incomplete/);
    assert.match(out.stdout, /relay cleanup: 3 file\(s\) deleted \(partial\)/);
    assertNoPaths(out, dir, files.oldCached, files.oldOutgoing, files.oldConvert, files.oldMessagesCopy, empty);
    assert.ok(existsSync(files.oldCached));
    assert.ok(existsSync(empty));
    assert.ok(!existsSync(files.oldMessagesCopy));
  } finally {
    chmodSync(unwritable, 0o700);
    chmodSync(pruneParent, 0o700);
    rmSync(dir, {recursive: true, force: true});
  }
});

test('relay cleanup --plist prints a weekly launchd agent that runs this script', {skip: !bash && 'bash is not available'}, () => {
  const out = run('/Users/relay', ['--plist']);
  assert.equal(out.status, 0, out.stderr);
  assert.match(out.stdout, /<key>Label<\/key><string>com\.skippercast\.relay-cleanup<\/string>/);
  assert.match(out.stdout, /<string>\/bin\/bash<\/string><string>\/.+\/scripts\/advisor\/relay-cleanup\.sh<\/string>/);
  assert.match(out.stdout, /<key>Weekday<\/key><integer>0<\/integer><key>Hour<\/key><integer>4<\/integer>/);
  assert.match(out.stdout, /\/Users\/relay\/Library\/Logs\/com\.skippercast\.relay-cleanup\.log/);
});
