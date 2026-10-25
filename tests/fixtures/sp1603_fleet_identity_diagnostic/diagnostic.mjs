// Strict evidence diagnostic. Exit 1 is honest unresolved parity; exit 2 is
// unexpected error. A green wrapper must check the complete expected-red report.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync, mkdirSync, existsSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, '../../..');
export const pins = JSON.parse(readFileSync(path.join(HERE, 'pins.json'), 'utf8'));
export const sha = bytes => createHash('sha256').update(bytes).digest('hex');
export const load = name => JSON.parse(readFileSync(name, 'utf8'));
export const save = (name, value) => writeFileSync(name, JSON.stringify(value, null, 2) + '\n');
export const families = ['exponent_parity', 'astral_key_parity'];

export function child(argv, directory, label) {
  mkdirSync(directory, {recursive: true});
  const start = new Date().toISOString(), clock = performance.now();
  const result = spawnSync(argv[0], argv.slice(1), {cwd: ROOT, encoding: 'utf8', timeout: 120000, maxBuffer: 16 * 1024 * 1024,
    env: {...process.env, TMPDIR: directory, SKIPPERCAST_ROOT: ROOT, SKIPPERCAST_FLEET_VAR: path.join(directory, 'synthetic-fleet')}});
  const stdout = result.stdout ?? '', stderr = result.stderr ?? '';
  writeFileSync(path.join(directory, `${label}.stdout`), stdout);
  writeFileSync(path.join(directory, `${label}.stderr`), stderr);
  const receipt = {argv, cwd: ROOT, started_at: start, duration_ms: performance.now() - clock,
    exit: result.status, signal: result.signal, error: result.error?.code ?? null,
    stdout_sha256: sha(stdout), stderr_sha256: sha(stderr), stdout: `${label}.stdout`, stderr: `${label}.stderr`};
  save(path.join(directory, `${label}.receipt.json`), receipt);
  return {receipt, stdout, stderr};
}

export function checkPins(fixture) {
  for (const [relative, expected] of Object.entries(pins.sources)) {
    if (sha(readFileSync(path.join(ROOT, relative))) !== expected) throw Error(`SOURCE_HASH_MISMATCH:${relative}`);
  }
  if (sha(readFileSync(fixture)) !== pins.corpus_sha256) throw Error('FIXTURE_HASH_MISMATCH');
}

export function evaluate(corpus, python, worker) {
  // Independently derive hashes from returned UTF-8 bytes, never an encoder oracle.
  const expectedIds = corpus.cases.map(c => c.id);
  if (new Set(expectedIds).size !== expectedIds.length) throw Error('DUPLICATE_FIXTURE_ID');
  for (const report of [python, worker]) {
    if (report.source_sha256 !== pins.sources[report.source] || !report.runtime?.version || !report.runtime?.executable) throw Error('PRODUCER_IDENTITY_MISMATCH');
    if (JSON.stringify(report.rows.map(r => r.id)) !== JSON.stringify(expectedIds)) throw Error('PRODUCER_CASE_SET_MISMATCH');
    for (const row of report.rows) {
      if (!/^(?:[0-9a-f]{2})*$/.test(row.utf8_hex) || Buffer.from(row.text, 'utf8').toString('hex') !== row.utf8_hex) throw Error(`BYTE_INTEGRITY:${row.id}`);
      const derived = sha(Buffer.from(row.utf8_hex, 'hex')).slice(0, 16);
      if (row.value_key !== derived) throw Error(`VALUE_KEY_INTEGRITY:${row.id}`);
      row.independently_derived_value_key = derived;
    }
  }
  if (python.source !== 'src/skippercast/fleet/ops.py' || worker.source !== 'server/fleet/ids.ts') throw Error('WRONG_PRODUCER_ROLES');
  const cases = corpus.cases.map((c, i) => ({id: c.id, family: c.family, python: python.rows[i], worker: worker.rows[i],
    equal: python.rows[i].utf8_hex === worker.rows[i].utf8_hex && python.rows[i].value_key === worker.rows[i].value_key}));
  const controls = cases.filter(c => c.family === 'control');
  if (controls.length !== 13 || controls.some(c => !c.equal)) throw Error('ORDINARY_CONTROL_FAILURE');
  for (const family of families) {
    const group = cases.filter(c => c.family === family);
    if (group.length !== 2 || group.some(c => c.equal)) throw Error(`UNEXPECTED_AGREEMENT_OR_MISSING_SUBCASE:${family}`);
  }
  if (cases.length !== 17 || cases.some(c => c.family !== 'control' && !families.includes(c.family))) throw Error('UNEXPECTED_CASE_CLASS');
  // Frozen measured premises supplement the independent derivation above.
  const byId = Object.fromEntries(cases.map(c => [c.id, c]));
  if (byId.exponent.python.text !== '1e-05' || byId.exponent.worker.text !== '0.00001' ||
      byId.ordinary_fraction.python.text !== '1.5' || byId.ordinary_fraction.worker.text !== '1.5') throw Error('MEASURED_PREMISE_CHANGED');
  const assertions = families.map(id => {
    try {
      for (const item of cases.filter(c => c.family === id)) {
        assert.equal(item.python.utf8_hex, item.worker.utf8_hex, item.id);
        assert.equal(item.python.value_key, item.worker.value_key, item.id);
      }
      return {id, passed: true};
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      return {id, passed: false, error: error.message};
    }
  });
  return {schema: 'skippercast.fleet-identity-diagnostic/v1', spec_version: pins.spec_version, id: pins.id,
    status: 'PARITY_UNRESOLVED', strict_exit: 1, mismatch_ids: assertions.filter(t => !t.passed).map(t => t.id),
    counts: {root_tests: 2, passed: 0, failed: 2, controls: controls.length, cases: cases.length, skipped: 0},
    assertions, source_hashes: pins.sources, corpus_sha256: pins.corpus_sha256,
    runtimes: {python: python.runtime, worker: worker.runtime}, cases};
}

// Ordinary discovery also runs in CI checkouts with setup-python but no stage.
// Explicit runtimes (including the acceptance launcher's staged path) never fall
// back. Producer runtime.executable and the child argv retain the actual choice.
export function discoveryPython() {
  const staged = path.join(ROOT, '.venv/bin/python3');
  return existsSync(staged) ? staged : 'python3';
}

export function collect(directory, {fixture = path.join(HERE, 'corpus.json'), python = discoveryPython()} = {}) {
  checkPins(fixture);
  const p = child([python, path.join(HERE, 'python_entry.py'), 'producer', '--fixture', fixture, '--output', directory], directory, 'python-producer');
  if (p.receipt.exit !== 0 || p.receipt.error) throw Error(`PYTHON_RUNTIME_FAILURE:${p.receipt.error ?? p.receipt.exit}`);
  const w = child([process.execPath, path.join(HERE, 'worker_entry.mjs'), fixture], directory, 'worker-producer');
  if (w.receipt.exit !== 0 || w.receipt.error) throw Error(`WORKER_RUNTIME_FAILURE:${w.receipt.error ?? w.receipt.exit}`);
  const report = evaluate(load(fixture), JSON.parse(p.stdout), JSON.parse(w.stdout));
  save(path.join(directory, 'diagnostic.json'), report);
  return report;
}

function main() {
  const args = process.argv.slice(2), options = {};
  if (args.length % 2) throw Error('expected option/value pairs');
  for (let i = 0; i < args.length; i += 2) {
    if (!['--output', '--fixture', '--python'].includes(args[i]) || options[args[i]] !== undefined) throw Error('unknown or duplicate option');
    options[args[i]] = path.resolve(args[i + 1]);
  }
  if (!options['--output']) throw Error('--output required');
  const report = collect(options['--output'], {fixture: options['--fixture'], python: options['--python']});
  console.log(JSON.stringify({status: report.status, strict_exit: 1, mismatch_ids: report.mismatch_ids, counts: report.counts}));
  process.exitCode = 1;
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { main(); } catch (error) {
    console.error(JSON.stringify({status: 'UNEXPECTED_ERROR', error: error.message}));
    process.exitCode = 2;
  }
}
