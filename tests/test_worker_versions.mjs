import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {liveVersion, commitOf, rollbackTarget, liveCommit, traceLiveCommit} from '../scripts/worker_versions.mjs';

// Modelled on deploy run 38173947179 (#568): the previous commit's code and secrets
// deployments, then the failed commit's code (be6f…) and secrets (04a1…) deployments.
const PREV_SHA = '1111111111111111111111111111111111111111';
const CUR_SHA = 'dabb9c249e2aa53fb4ae9b8d30e1ab7c5f4f9e01';
const PREV_CODE = 'a1b2c3d4-0000-4000-8000-000000000001';
const PREV_SECRETS = 'a1b2c3d4-0000-4000-8000-000000000002';
const CUR_CODE = 'be6f3ab6-0000-4000-8000-000000000003';
const CUR_SECRETS = '04a1aa00-0000-4000-8000-000000000004';

const deployment = (id, at, version, source) =>
  ({id, created_on: at, source, strategy: 'percentage', versions: [{version_id: version, percentage: 100}]});
// `wrangler deployments list --json` prints oldest first.
const DEPLOYMENTS = [
  deployment('d1', '2026-10-10T18:00:00.000Z', PREV_CODE, 'wrangler'),
  deployment('d2', '2026-10-10T18:00:06.000Z', PREV_SECRETS, 'wrangler'),
  deployment('d3', '2026-10-11T09:00:00.000Z', CUR_CODE, 'wrangler'),
  deployment('d4', '2026-10-11T09:00:05.000Z', CUR_SECRETS, 'wrangler'),
];
const version = (id, at, message) => ({
  id, metadata: {created_on: at, source: 'wrangler', author_email: 'ci@example.com'},
  ...(message ? {annotations: {'workers/message': message, 'workers/triggered_by': 'upload'}} : {annotations: {'workers/triggered_by': 'secret'}}),
});
const VERSIONS = [
  version(PREV_CODE, '2026-10-10T18:00:00.000Z', `${PREV_SHA} run 38100000000`),
  version(PREV_SECRETS, '2026-10-10T18:00:06.000Z'),
  version(CUR_CODE, '2026-10-11T09:00:00.000Z', `${CUR_SHA} run 38173947179`),
  version(CUR_SECRETS, '2026-10-11T09:00:05.000Z'),
];

test('the live version is the newest deployment\'s 100% version, whatever the listing order', () => {
  assert.equal(liveVersion(DEPLOYMENTS), CUR_SECRETS);
  assert.equal(liveVersion([...DEPLOYMENTS].reverse()), CUR_SECRETS);
  assert.equal(liveVersion([]), '');
  assert.equal(liveVersion([{id: 'x', created_on: '2026-10-11T00:00:00Z', versions: [{version_id: 'v', percentage: 50}]}]), '');
});

test('the deploy step records the version that served before the code deploy', () => {
  // What cloudflare_deploy.sh sees right before `wrangler deploy` in the failed run.
  assert.equal(liveVersion(DEPLOYMENTS.slice(0, 2)), PREV_SECRETS);
});

test('a version\'s commit comes from its deploy message', () => {
  assert.equal(commitOf(VERSIONS[2]), CUR_SHA);
  assert.equal(commitOf(VERSIONS[3]), null);
  assert.equal(commitOf({}), null);
  assert.equal(commitOf(undefined), null);
});

test('the rollback target is the version live before the failed commit\'s deploy', () => {
  // The previous commit's secrets upload carries its final secrets; its code version does not.
  assert.equal(rollbackTarget(DEPLOYMENTS, VERSIONS), PREV_SECRETS);
  assert.notEqual(rollbackTarget(DEPLOYMENTS, VERSIONS), CUR_CODE);
  assert.notEqual(rollbackTarget(DEPLOYMENTS, VERSIONS), PREV_CODE);
  // Live on the code version itself (no secrets upload): same answer.
  assert.equal(rollbackTarget(DEPLOYMENTS.slice(0, 3), VERSIONS), PREV_SECRETS);
  // An explicit commit to skip: nothing is older than the previous commit here.
  assert.equal(rollbackTarget(DEPLOYMENTS, VERSIONS, {excludeCommit: PREV_SHA}), '');
});

test('a previous commit with only a code version (no secrets upload) is the target', () => {
  const versions = [VERSIONS[0], VERSIONS[2], VERSIONS[3]];
  assert.equal(rollbackTarget(DEPLOYMENTS, versions), PREV_CODE);
});

test('no target when there is no earlier version from a different commit', () => {
  assert.equal(rollbackTarget([], VERSIONS), '');
  assert.equal(rollbackTarget(DEPLOYMENTS, []), '');
  assert.equal(rollbackTarget(DEPLOYMENTS.slice(2), VERSIONS.slice(2)), '');
  assert.equal(rollbackTarget(DEPLOYMENTS.slice(0, 2), VERSIONS.slice(0, 2)), '');
});

const script = fileURLToPath(new URL('../scripts/worker_versions.mjs', import.meta.url));
function cli(deployments, versions, ...args) {
  const dir = mkdtempSync(join(tmpdir(), 'worker-versions-'));
  try {
    writeFileSync(join(dir, 'deployments.json'), JSON.stringify(deployments));
    writeFileSync(join(dir, 'versions.json'), JSON.stringify(versions));
    return spawnSync(process.execPath, [script, ...args.map(a => a.replace(/^@/, dir + '/'))], {encoding: 'utf8'});
  } finally { rmSync(dir, {recursive: true, force: true}); }
}

test('the CLI prints the live version and the rollback target', () => {
  let run = cli(DEPLOYMENTS, VERSIONS, 'live', '@deployments.json');
  assert.equal(run.status, 0, run.stderr);
  assert.equal(run.stdout.trim(), CUR_SECRETS);
  run = cli(DEPLOYMENTS, VERSIONS, 'rollback-target', '@deployments.json', '@versions.json');
  assert.equal(run.status, 0, run.stderr);
  assert.equal(run.stdout.trim(), PREV_SECRETS);
  run = cli(DEPLOYMENTS, VERSIONS, 'commit', '@versions.json', PREV_CODE);
  assert.equal(run.stdout.trim(), PREV_SHA);
});

test('the commit production serves is traced from the live version\'s provenance', () => {
  assert.equal(liveCommit(DEPLOYMENTS, VERSIONS), CUR_SHA, 'live is the secrets upload made right after its code deploy');
  assert.equal(liveCommit(DEPLOYMENTS.slice(0, 3), VERSIONS), CUR_SHA, 'live is the code upload itself');
  const codeLive = [...DEPLOYMENTS, deployment('d5', '2026-10-11T10:00:00.000Z', PREV_CODE, 'wrangler')];
  assert.equal(liveCommit(codeLive, VERSIONS), PREV_SHA, 'a rollback to an older code version');
  const rolledBack = [...DEPLOYMENTS, deployment('d5', '2026-10-11T10:00:00.000Z', PREV_SECRETS, 'wrangler')];
  assert.equal(liveCommit(rolledBack, VERSIONS), PREV_SHA, 'a rollback to the previous commit\'s secrets upload');
  // A later secrets change on top of the secrets upload: the chain is followed.
  const later = [...VERSIONS, version('05050505-0000-4000-8000-000000000005', '2026-10-11T12:00:00.000Z')];
  const laterLive = [...DEPLOYMENTS, deployment('d5', '2026-10-11T12:00:00.000Z', '05050505-0000-4000-8000-000000000005', 'wrangler')];
  assert.equal(liveCommit(laterLive, later), CUR_SHA);
});

test('a version made by "version_upload" (the pipeline\'s own wrangler deploy) is traced like "upload"', () => {
  // Cloudflare annotates the pipeline's `wrangler deploy --message "<sha> run <id>"` as "version_upload".
  const code = (id, at, message, triggeredBy) => ({
    id, metadata: {created_on: at, source: 'wrangler', author_email: 'ci@example.com'},
    annotations: message ? {'workers/message': message, 'workers/triggered_by': triggeredBy}
                         : {'workers/triggered_by': triggeredBy},
  });
  const vCode = code(CUR_CODE, '2026-10-11T09:00:00.000Z', `${CUR_SHA} run 38173947179`, 'version_upload');
  const versions = [VERSIONS[0], VERSIONS[1], vCode, VERSIONS[3]];
  assert.equal(liveCommit(DEPLOYMENTS.slice(0, 3), versions), CUR_SHA, 'the code upload itself');
  assert.equal(liveCommit(DEPLOYMENTS, versions), CUR_SHA, 'a secrets change chained onto the version_upload');

  // A free-form message names no commit, whatever the trigger.
  const freeform = code(CUR_CODE, '2026-10-11T09:00:00.000Z', `hotfix on top of ${CUR_SHA}`, 'version_upload');
  const freeformTrace = traceLiveCommit(DEPLOYMENTS.slice(0, 3), [VERSIONS[0], VERSIONS[1], freeform, VERSIONS[3]]);
  assert.equal(freeformTrace.commit, '');
  assert.match(freeformTrace.reason, /no "<sha> run <id>" deploy message/);

  // A version_upload with no message is unknown, never guessed.
  const missing = code(CUR_CODE, '2026-10-11T09:00:00.000Z', null, 'version_upload');
  const missingTrace = traceLiveCommit(DEPLOYMENTS.slice(0, 3), [VERSIONS[0], VERSIONS[1], missing, VERSIONS[3]]);
  assert.equal(missingTrace.commit, '');
  assert.match(missingTrace.reason, /no "<sha> run <id>" deploy message/);
});

test('a live commit that cannot be traced is unknown, never guessed', () => {
  const unknown = (deployments, versions, reason) => {
    const traced = traceLiveCommit(deployments, versions);
    assert.equal(traced.commit, '', `${reason}: ${traced.reason}`);
    assert.equal(liveCommit(deployments, versions), '');
    return traced.reason;
  };
  // Sol's probe: an untagged CODE upload is live; the older tagged version must not be named.
  const HAND = '0a0a0a0a-0000-4000-8000-00000000000a';
  const untagged = [...VERSIONS, {id: HAND, metadata: {created_on: '2026-10-11T11:00:00.000Z'}, annotations: {'workers/triggered_by': 'upload'}}];
  const handLive = [...DEPLOYMENTS, deployment('d5', '2026-10-11T11:00:00.000Z', HAND, 'wrangler')];
  assert.match(unknown(handLive, untagged, 'untagged code upload'), /no "<sha> run <id>" deploy message/);
  // A hand-labelled upload whose message merely contains a sha.
  const labelled = [...VERSIONS, version(HAND, '2026-10-11T11:00:00.000Z', `hotfix on top of ${PREV_SHA}`)];
  unknown(handLive, labelled, 'free-form message');
  // A version with no or another trigger.
  for (const trigger of [undefined, 'rollback', 'promotion']) {
    const odd = [...VERSIONS, {id: HAND, metadata: {created_on: '2026-10-11T11:00:00.000Z'},
      annotations: {...(trigger ? {'workers/triggered_by': trigger} : {}), 'workers/message': `${PREV_SHA} run 1`}}];
    assert.match(unknown(handLive, odd, `trigger ${trigger}`), /no traceable commit/);
  }
  // A staged upload between the code version and a secrets change: the secrets change's code is not provable.
  const STAGED = '0b0b0b0b-0000-4000-8000-00000000000b';
  const SECRET2 = '0c0c0c0c-0000-4000-8000-00000000000c';
  const staged = [...VERSIONS, version(STAGED, '2026-10-11T11:00:00.000Z', `${PREV_SHA} run 5`), version(SECRET2, '2026-10-11T11:30:00.000Z')];
  const stagedLive = [...DEPLOYMENTS, deployment('d5', '2026-10-11T11:30:00.000Z', SECRET2, 'wrangler')];
  assert.match(unknown(stagedLive, staged, 'staged upload'), /was not the 100% deployment then/);
  // A secrets change made after a rollback (dashboard): the newest version was not live when it was made.
  const afterRollback = [...VERSIONS, version(SECRET2, '2026-10-11T11:30:00.000Z')];
  const rollbackThenSecret = [...DEPLOYMENTS, deployment('d5', '2026-10-11T11:00:00.000Z', PREV_CODE, 'wrangler'),
    deployment('d6', '2026-10-11T11:30:00.000Z', SECRET2, 'wrangler')];
  assert.match(unknown(rollbackThenSecret, afterRollback, 'secrets after rollback'), /was not the 100% deployment then/);
  // Split traffic, missing versions or deployments, and malformed listings.
  const split = [...DEPLOYMENTS, {id: 'g', created_on: '2026-10-11T10:00:00Z',
    versions: [{version_id: CUR_SECRETS, percentage: 50}, {version_id: PREV_SECRETS, percentage: 50}]}];
  assert.match(unknown(split, VERSIONS, 'split'), /split traffic/);
  assert.match(unknown(DEPLOYMENTS, VERSIONS.slice(0, 3), 'live missing'), /not in the versions listing/);
  assert.match(unknown(DEPLOYMENTS, [VERSIONS[3]], 'code version cut off'), /created before secrets change/);
  assert.match(unknown(DEPLOYMENTS.slice(3), VERSIONS, 'deployment history cut off'), /was not the 100% deployment then/);
  assert.match(unknown([], VERSIONS, 'no deployments'), /no Worker deployment/);
  unknown({}, VERSIONS, 'not a list');
  unknown([{...DEPLOYMENTS[3], created_on: 'soon'}], VERSIONS, 'bad deployment time');
  unknown(DEPLOYMENTS, [...VERSIONS, {id: 'x', metadata: {}}], 'bad version time');
});

test('the live-commit CLI prints the traced commit or exits 1 with the reason', () => {
  let run = cli(DEPLOYMENTS, VERSIONS, 'live-commit', '@deployments.json', '@versions.json');
  assert.equal(run.status, 0, run.stderr);
  assert.equal(run.stdout.trim(), CUR_SHA);
  run = cli(DEPLOYMENTS, [VERSIONS[1], VERSIONS[3]], 'live-commit', '@deployments.json', '@versions.json');
  assert.equal(run.status, 1);
  assert.equal(run.stdout, '');
  assert.match(run.stderr, /^the commit production serves is unknown: /);
});

test('the CLI exits 1 with a message when there is nothing to roll back to', () => {
  let run = cli(DEPLOYMENTS.slice(2), VERSIONS.slice(2), 'rollback-target', '@deployments.json', '@versions.json');
  assert.equal(run.status, 1);
  assert.equal(run.stdout, '');
  assert.match(run.stderr, /no earlier Worker version/);
  // Live version missing from the (cut-off) listing.
  run = cli(DEPLOYMENTS, VERSIONS.slice(0, 3), 'rollback-target', '@deployments.json', '@versions.json');
  assert.equal(run.status, 1);
  assert.match(run.stderr, new RegExp(`live version ${CUR_SECRETS} is not in the versions listing; pass an explicit version id`));
  // Gradual deployment: no version at 100%.
  const gradual = [{id: 'g', created_on: '2026-10-11T10:00:00Z', versions: [{version_id: CUR_CODE, percentage: 50}, {version_id: PREV_SECRETS, percentage: 50}]}];
  run = cli(gradual, VERSIONS, 'rollback-target', '@deployments.json', '@versions.json');
  assert.equal(run.status, 1);
  assert.match(run.stderr, /no version serves 100% of traffic; pass an explicit version id/);
  run = cli([], [], 'live', '@deployments.json');
  assert.equal(run.status, 1);
  assert.match(run.stderr, /no deployment/);
  assert.equal(cli([], [], 'bogus').status, 2);
});

test('the deploy workflow never runs a bare wrangler rollback', () => {
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  const rollbacks = [...workflow.matchAll(/\$WRANGLER rollback\b(.*)/g)].map(m => m[1].trim());
  assert.equal(rollbacks.length, 2, 'the automatic and the manual rollback');
  for (const args of rollbacks) assert.match(args, /^"\$(PREVIOUS|target)" --config /, `rollback without a version id: ${args}`);
  assert.doesNotMatch(workflow, /wrangler(@[\d.]+)? rollback --config/);
  assert.match(workflow, /steps\.deploy\.outputs\.previous_version/);
  // Each rollback is followed by a check of the live Worker version, not of the build id.
  const parts = workflow.split(/\$WRANGLER rollback\b/).slice(1);
  assert.equal(parts.length, 2);
  for (const part of parts) {
    assert.match(part, /deployments list --json[^\n]*> var\/deployments\.json[\s\S]*?worker_versions\.mjs live var\/deployments\.json/);
  }
  const deploy = readFileSync(new URL('../scripts/cloudflare_deploy.sh', import.meta.url), 'utf8');
  assert.match(deploy, /previous_version=\$previous_version" >> "\$GITHUB_OUTPUT"/);
  assert.match(deploy, /build=\$build" >> "\$GITHUB_OUTPUT"/);
});

test('a deploy or rollback that cannot be smoke-tested fails instead of passing with a warning', () => {
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  // Every unset-address branch exits 1 with an error; none exits 0.
  const unset = [...workflow.matchAll(/if \[ -z "\$SITE" \]; then (.*)/g)].map(m => m[1]);
  assert.ok(unset.length >= 2, 'the deploy and rollback smoke steps check the address');
  for (const branch of unset) assert.doesNotMatch(branch, /exit 0/, `unset CLOUDFLARE_SITE_URL passes: ${branch}`);
  assert.doesNotMatch(workflow, /::warning::Set the CLOUDFLARE_SITE_URL/);
  // The address is required before the deploy step writes anything.
  const preflight = workflow.indexOf('Require a smoke-test address before deploying');
  assert.ok(preflight > 0 && preflight < workflow.indexOf('id: deploy'), 'the address check runs before the deploy');
  assert.match(workflow.slice(preflight, workflow.indexOf('id: deploy')), /\[ -n "\$CLOUDFLARE_API_TOKEN" \] && \[ -n "\$CLOUDFLARE_ACCOUNT_ID" \] && \[ -z "\$SITE" \]; then\n\s+echo "::error::[^\n]*"\n\s+exit 1/);
  // Unconfigured Cloudflare (a fork without the secrets) still deploys nothing rather than failing.
});
