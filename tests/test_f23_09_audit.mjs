import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {test} from 'node:test';

const workflow = readFileSync(new URL('../.github/workflows/fleet-health.yml', import.meta.url), 'utf8');
// Replay the checked-in decision/output block, not the network or issue steps.
const decision = workflow.match(/^        id: health\n        run: \|\n[\s\S]*?^          (if [\s\S]*?)(?=^      - name:)/m)?.[1];
assert.ok(decision, 'missing health decision');
assert.doesNotMatch(decision, /\b(?:curl|gh)\b/);

const fresh = {age_s: 60, stale: false};
const checks = {heartbeat: fresh, last_message: fresh, processed: fresh};
const healthy = {stale_after_s: 10800, stale: false, checks};
const late = {...checks, processed: {age_s: null, stale: true}};

// A truthy checks object or a false-looking flag is not evidence of recovery.
for (const [name, body, stale, unknown = true] of [
  ['empty checks with no aggregate', {stale_after_s: 10800, checks: {}}, true],
  ['missing processor check', {...healthy, checks: {heartbeat: fresh, last_message: fresh}}, true],
  ['wrong name at the expected check count', {...healthy, checks: {heartbeat: fresh, last_message: fresh, processor: fresh}}, true],
  ['missing per-check status', {...healthy, checks: {...checks, heartbeat: {age_s: 60}}}, true],
  ['string per-check status', {...healthy, checks: {...checks, last_message: {...fresh, stale: 'false'}}}, true],
  // The recovery path must not close an incident on a reply the message builder cannot read.
  ['missing stale_after_s', {stale: false, checks}, true],
  ['string stale_after_s', {...healthy, stale_after_s: '10800'}, true],
  ['missing age_s', {...healthy, checks: {...checks, processed: {stale: false}}}, true],
  ['string age_s', {...healthy, checks: {...checks, processed: {age_s: '60', stale: false}}}, true],
  ['missing aggregate with complete checks', {stale_after_s: 10800, checks}, true],
  ['string aggregate', {...healthy, stale: 'false'}, true],
  ['aggregate hides a stale check', {...healthy, checks: late}, true],
  ['aggregate claims staleness with all checks fresh', {...healthy, stale: true}, true],
  ['more than one JSON reply', `${JSON.stringify(healthy)}\n${JSON.stringify(healthy)}`, true],
  ['malformed JSON', '{', true],
  ['complete stale reply', {...healthy, stale: true, checks: late}, true, false],
  ['complete healthy reply', healthy, false, false],
]) {
  test(`AIS health: ${name}`, (t) => {
    const dir = mkdtempSync(join(tmpdir(), 'fleet-health-'));
    t.after(() => rmSync(dir, {recursive: true, force: true}));
    const script = join(dir, 'decision.sh');
    const summary = join(dir, 'summary');
    const output = join(dir, 'output');
    writeFileSync(script, `set +e -uo pipefail\nbody=$1\nREGION=ZZ\nGITHUB_STEP_SUMMARY=$2\nGITHUB_OUTPUT=$3\ntrue\n${decision}`);
    const reply = typeof body === 'string' ? body : JSON.stringify(body);
    const run = spawnSync('bash', [script, reply, summary, output], {
      encoding: 'utf8', env: {PATH: process.env.PATH}, timeout: 5000,
    });
    assert.ifError(run.error);
    assert.equal(run.status, 0, run.stderr);
    assert.deepEqual(readFileSync(output, 'utf8').split('\n').filter(line => line.startsWith('stale=')), [`stale=${stale}`]);
    const note = readFileSync(summary, 'utf8');
    if (unknown) assert.match(note, /health for ZZ is unknown/);
    else assert.match(note, /health for ZZ \(stale after 3 h\)/);
  });
}
