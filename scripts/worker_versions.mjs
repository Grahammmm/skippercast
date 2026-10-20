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
//   node scripts/worker_versions.mjs live-commit <deployments.json> <versions.json>   (the commit production serves, traced; exit 1 when unknown)
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

// The exact message cloudflare_deploy.sh gives a code version ("<sha> run <run id>"), or null.
// Stricter than commitOf: a free-form message that happens to contain a sha names no commit.
const DEPLOY_MESSAGE = /^([0-9a-f]{40}) run [0-9]+$/;
const stamp = value => {
  const at = Date.parse(value ?? '');
  return Number.isFinite(at) ? at : null;
};
const fullTraffic = deployment => {
  const served = Array.isArray(deployment?.versions) ? deployment.versions : [];
  return served.length === 1 && Number(served[0]?.percentage) === 100 ? served[0].version_id ?? '' : '';
};

// The commit production serves, traced from the live version's provenance, with the reason
// when it cannot be traced ({commit: '', reason}). The deploy workflow holds a deploy of that
// commit or an older one, and holds every deploy when the commit cannot be traced.
//   - A code upload (workers/triggered_by "upload") names its commit in the deploy message.
//   - A secrets change ("secret") copies the code of the version created just before it, and
//     Cloudflare refuses one unless that version is deployed; so it is traced to that version
//     only when the newest deployment older than the change served that version at 100%.
//     Chains of secrets changes are followed the same way.
//   - Anything else (split traffic, an untagged or hand-labelled upload, another trigger, a
//     version or deployment missing from the listings) is unknown, never guessed.
export function traceLiveCommit(deployments = [], versions = []) {
  const unknown = reason => ({commit: '', reason});
  if (!Array.isArray(deployments) || !Array.isArray(versions)) return unknown('the Wrangler listings are not lists');
  if (deployments.some(d => stamp(d?.created_on) === null)) return unknown('a deployment has no valid creation time');
  if (versions.some(v => stamp(v?.metadata?.created_on) === null)) return unknown('a version has no valid creation time');
  const history = [...deployments].sort((a, b) => stamp(b.created_on) - stamp(a.created_on));
  if (!history.length) return unknown('no Worker deployment exists');
  let id = fullTraffic(history[0]);
  if (!id) return unknown('the newest deployment does not serve exactly one version at 100% (split traffic)');
  const byCreation = [...versions].sort((a, b) => stamp(b.metadata.created_on) - stamp(a.metadata.created_on));
  for (let hops = 0; hops <= versions.length; hops++) {
    const version = versions.find(v => v?.id === id);
    if (!version) return unknown(`version ${id} is not in the versions listing`);
    const at = stamp(version.metadata.created_on);
    const trigger = version.annotations?.['workers/triggered_by'];
    if (trigger === 'upload') {
      const match = DEPLOY_MESSAGE.exec(version.annotations?.['workers/message'] ?? '');
      return match ? {commit: match[1], reason: `version ${id} was deployed from ${match[1]}`}
        : unknown(`code version ${id} has no "<sha> run <id>" deploy message`);
    }
    if (trigger !== 'secret') return unknown(`version ${id} was made by ${trigger ? `"${trigger}"` : 'an unrecorded trigger'}, so its code has no traceable commit`);
    const before = byCreation.find(v => stamp(v.metadata.created_on) < at);
    if (!before) return unknown(`the version created before secrets change ${id} is not in the versions listing`);
    const servedThen = history.find(d => stamp(d.created_on) < at);
    if (!servedThen || fullTraffic(servedThen) !== before.id) {
      return unknown(`secrets change ${id} cannot be traced: version ${before.id}, created just before it, was not the 100% deployment then`);
    }
    id = before.id;
  }
  return unknown('the version history does not end in a code upload');
}

// The commit production serves, or '' when it cannot be traced (see traceLiveCommit).
export function liveCommit(deployments = [], versions = []) {
  return traceLiveCommit(deployments, versions).commit;
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
    const traced = traceLiveCommit(readJson(files[0]), readJson(files[1]));
    answer = traced.commit;
    missing = `the commit production serves is unknown: ${traced.reason}`;
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
