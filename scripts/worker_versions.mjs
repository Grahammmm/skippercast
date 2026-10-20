#!/usr/bin/env node
// Pick Worker versions for a rollback from Wrangler's JSON listings.
// A deploy makes two deployments a few seconds apart: `wrangler deploy` (the code,
// with message "<sha> run <run id>") and `wrangler secret bulk` (a new version of
// the same code with no message). A bare `wrangler rollback` skips only the newest
// deployment, so it lands on the code version of the commit that just failed
// (#568). These helpers name the version to roll back to instead: the version live
// before the current commit's deploy.
// Usage (the files hold `wrangler deployments list --json` / `versions list --json`):
//   node scripts/worker_versions.mjs live <deployments.json>
//   node scripts/worker_versions.mjs rollback-target <deployments.json> <versions.json>   (the version live before the current commit's deploy)
//   node scripts/worker_versions.mjs commit <versions.json> <version-id>
//   node scripts/worker_versions.mjs live-commit <deployments.json> <versions.json>   (the commit production serves)
// Each prints one id (or sha) and exits 1 with a message on stderr when there is none.
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const time = value => Date.parse(value ?? '') || 0;

// The version serving 100% of traffic in the newest deployment, or ''.
export function liveVersion(deployments = []) {
  const newest = [...deployments].sort((a, b) => time(b.created_on) - time(a.created_on))[0];
  return newest?.versions?.find(v => Number(v.percentage) === 100)?.version_id ?? '';
}

// The commit sha in a version's deploy message ("<40-hex sha> run <run id>"), or null.
export function commitOf(version) {
  const match = /\b[0-9a-f]{40}\b/.exec(version?.annotations?.['workers/message'] ?? '');
  return match ? match[0] : null;
}

const created = version => time(version?.metadata?.created_on);

// The version that was live just before the excluded commit's deploy: the newest version
// older than the earliest version of that commit. That is the previous commit's secrets
// upload when it has one (it carries that commit's final secrets), else its code version.
// Versions with no commit (secrets uploads) qualify. excludeCommit defaults to the live
// version's commit or, when the live version is a secrets upload (no message), the commit
// of the newest earlier version that has one. Returns '' when nothing qualifies.
export function rollbackTarget(deployments = [], versions = [], {excludeCommit} = {}) {
  const liveId = liveVersion(deployments);
  const live = versions.find(v => v.id === liveId);
  if (!live) return '';
  const older = versions.filter(v => v.id !== liveId && created(v) < created(live))
    .sort((a, b) => created(b) - created(a));
  const exclude = excludeCommit === undefined
    ? commitOf(live) ?? older.map(commitOf).find(Boolean) ?? null
    : excludeCommit;
  if (!exclude) return '';
  const first = Math.min(...versions.filter(v => commitOf(v) === exclude).map(created));
  if (!Number.isFinite(first)) return '';
  return versions.filter(v => created(v) < first)
    .sort((a, b) => created(b) - created(a))[0]?.id ?? '';
}

// The commit production serves: the live version's own commit or, when the live version is a
// secrets upload (no message), the commit of the newest earlier version that has one. The deploy
// workflow holds a deploy of that commit or an older one. Returns '' when it cannot be named.
export function liveCommit(deployments = [], versions = []) {
  const liveId = liveVersion(deployments);
  const live = versions.find(v => v.id === liveId);
  if (!live) return '';
  return commitOf(live) ?? versions.filter(v => v.id !== liveId && created(v) < created(live))
    .sort((a, b) => created(b) - created(a)).map(commitOf).find(Boolean) ?? '';
}

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [command, ...files] = process.argv.slice(2);
  let answer, missing;
  if (command === 'live' && files.length === 1) {
    answer = liveVersion(readJson(files[0]));
    missing = 'no deployment serves a version at 100%';
  } else if (command === 'rollback-target' && files.length === 2) {
    const deployments = readJson(files[0]), versions = readJson(files[1]);
    const liveId = liveVersion(deployments);
    if (!liveId) {
      console.error('no version serves 100% of traffic; pass an explicit version id');
      process.exit(1);
    }
    if (!versions.some(v => v.id === liveId)) {
      console.error(`live version ${liveId} is not in the versions listing; pass an explicit version id`);
      process.exit(1);
    }
    answer = rollbackTarget(deployments, versions);
    missing = 'no earlier Worker version from before the current commit\'s deploy to roll back to';
  } else if (command === 'live-commit' && files.length === 2) {
    answer = liveCommit(readJson(files[0]), readJson(files[1]));
    missing = 'the live version and the versions before it name no commit';
  } else if (command === 'commit' && files.length === 2) {
    answer = commitOf(readJson(files[0]).find(v => v.id === files[1])) ?? '';
    missing = `version ${files[1]} has no commit in its deploy message`;
  } else {
    console.error('usage: worker_versions.mjs live <deployments.json> | rollback-target <deployments.json> <versions.json> (the version live before the current commit\'s deploy) | commit <versions.json> <version-id> | live-commit <deployments.json> <versions.json>');
    process.exit(2);
  }
  if (!answer) { console.error(missing); process.exit(1); }
  console.log(answer);
}
