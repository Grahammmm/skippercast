// CI requires SCA-369 parity. --baseline replays the frozen pre-fix evidence
// only on the pinned baseline sources, never as a fallback on a current tree.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {collect as collectBaseline, evaluate as evaluateBaseline, child, load, save, sha, pins,
  discoveryPython, HERE, ROOT, families} from './fixtures/sp1603_fleet_identity_diagnostic/diagnostic.mjs';

const baseline = process.argv[2] === '--baseline';
const fixture = path.join(HERE, 'corpus.json');
const python = discoveryPython();
const sources = {...pins.sources, ...pins.successor};
const roles = ['src/skippercast/fleet/ops.py', 'server/fleet/ids.ts'];
assert.deepEqual(Object.keys(pins.successor).sort(), [...roles].sort());
const evaluate = baseline ? evaluateBaseline : evaluateSuccessor;
const collect = baseline ? collectBaseline : collectSuccessor;

function evaluateSuccessor(corpus, python, worker) {
  const ids = corpus.cases.map(c => c.id);
  if (new Set(ids).size !== ids.length) throw Error('DUPLICATE_FIXTURE_ID');
  if (ids.length !== 17 || corpus.cases.filter(c => c.family === 'control').length !== 15 ||
      corpus.cases.filter(c => c.family === 'exponent_parity').length !== 2) throw Error('UNEXPECTED_CASE_CLASS');
  for (const producer of [python, worker]) {
    if (!Object.hasOwn(sources, producer.source) || producer.source_sha256 !== sources[producer.source] ||
        !producer.runtime?.version || !producer.runtime?.executable) throw Error('PRODUCER_IDENTITY_MISMATCH');
    if (JSON.stringify(producer.rows.map(r => r.id)) !== JSON.stringify(ids)) throw Error('PRODUCER_CASE_SET_MISMATCH');
    for (const row of producer.rows) {
      if (Buffer.from(row.text, 'utf8').toString('hex') !== row.utf8_hex) throw Error(`BYTE_INTEGRITY:${row.id}`);
      row.independently_derived_value_key = sha(Buffer.from(row.utf8_hex, 'hex')).slice(0, 16);
      if (row.value_key !== row.independently_derived_value_key) throw Error(`VALUE_KEY_INTEGRITY:${row.id}`);
    }
  }
  if (python.source !== roles[0] || worker.source !== roles[1]) throw Error('WRONG_PRODUCER_ROLES');
  const cases = corpus.cases.map(({id, family}, i) => {
    const p = python.rows[i], w = worker.rows[i];
    if (p.utf8_hex !== w.utf8_hex || p.value_key !== w.value_key) throw Error(`PARITY_MISMATCH:${family}:${id}`);
    return {id, family, python: p, worker: w, equal: true};
  });
  return {status: 'PARITY_RESOLVED', strict_exit: 0, mismatch_ids: [], source_hashes: sources, corpus_sha256: pins.corpus_sha256,
    runtimes: {python: python.runtime, worker: worker.runtime}, cases};
}

function collectSuccessor(directory, {fixture: input = fixture, python: runtime = python} = {}) {
  for (const [relative, expected] of Object.entries(sources)) {
    if (sha(readFileSync(path.join(ROOT, relative))) !== expected) throw Error(`SOURCE_HASH_MISMATCH:${relative}`);
  }
  if (sha(readFileSync(input)) !== pins.corpus_sha256) throw Error('FIXTURE_HASH_MISMATCH');
  const p = child([runtime, path.join(HERE, 'python_entry.py'), 'producer', '--fixture', input, '--output', directory], directory, 'python-producer');
  if (p.receipt.exit !== 0 || p.receipt.error) throw Error(`PYTHON_RUNTIME_FAILURE:${p.receipt.error ?? p.receipt.exit}`);
  const w = child([process.execPath, path.join(HERE, 'worker_entry.mjs'), input], directory, 'worker-producer');
  if (w.receipt.exit !== 0 || w.receipt.error) throw Error(`WORKER_RUNTIME_FAILURE:${w.receipt.error ?? w.receipt.exit}`);
  const report = evaluateSuccessor(load(input), JSON.parse(p.stdout), JSON.parse(w.stdout));
  save(path.join(directory, 'diagnostic.json'), report);
  return report;
}

if (process.argv[2] === '--successor') {
  try {
    const [output, input, runtime] = process.argv.slice(3);
    if (!output || process.argv.length > 6) throw Error('expected output [fixture [python]]');
    const report = collectSuccessor(path.resolve(output), {fixture: input && path.resolve(input), python: runtime});
    console.log(JSON.stringify({status: report.status, strict_exit: report.strict_exit, mismatch_ids: report.mismatch_ids}));
    process.exit(0);
  } catch (error) {
    console.error(JSON.stringify({status: 'UNEXPECTED_ERROR', error: error.message}));
    process.exit(2);
  }
}

const directory = mkdtempSync(path.join(process.env.SP1603_OUTPUT ?? tmpdir(), 'sp1603-characterization-'));
const corpus = load(fixture);
const report = collect(path.join(directory, 'positive'));
test('discovery selects staged Python when available, otherwise installed python3, and records actual runtime', () => {
  const staged = path.join(ROOT, '.venv/bin/python3');
  assert.equal(python, existsSync(staged) ? staged : 'python3');
  const receipt = load(path.join(directory, 'positive/python-producer.receipt.json'));
  assert.equal(receipt.argv[0], python);
  assert.equal(receipt.exit, 0);
  assert.ok(path.isAbsolute(report.runtimes.python.executable));
  assert.ok(existsSync(report.runtimes.python.executable));
  assert.ok(report.runtimes.python.version.length > 0);
});
for (const item of report.cases.filter(c => c.family === 'control')) {
  test(`A2 ordinary control: ${item.id}`, () => {
    assert.equal(item.equal, true);
    assert.equal(item.python.value_key, item.python.independently_derived_value_key);
    assert.equal(item.worker.value_key, item.worker.independently_derived_value_key);
  });
}
test('A1 measured exponent/control values and parity verdict for the selected sources', () => {
  const exponent = report.cases.find(c => c.id === 'exponent');
  if (baseline) {
    assert.equal(report.status, 'PARITY_UNRESOLVED');
    assert.equal(report.strict_exit, 1);
    assert.deepEqual(report.mismatch_ids, families);
    assert.deepEqual(report.counts, {root_tests: 1, passed: 0, failed: 1, controls: 15, cases: 17, skipped: 0});
    assert.equal(exponent.python.value_key, '5a9530d3c6d5faad');
  } else {
    assert.equal(report.status, 'PARITY_RESOLVED');
    assert.equal(report.strict_exit, 0);
    assert.deepEqual(report.mismatch_ids, []);
    assert.equal(report.cases.length, 17);
    assert.equal(exponent.python.value_key, '661710915adfa7c4');
  }
  assert.equal(exponent.worker.value_key, '661710915adfa7c4');
  assert.equal(report.cases.find(c => c.id === 'ordinary_fraction').worker.value_key, '9f29a130438b8117');
  const astral = report.cases.find(c => c.id === 'astral_keys');
  assert.equal(astral.python.text, '{"\ue000":1,"\u{10000}":2}');
  assert.equal(astral.worker.text, '{"\ue000":1,"\u{10000}":2}');
});
test('A3 nested evidence and actual bytes/keys deterministic across fresh producer processes', () => {
  const again = collect(path.join(directory, 'repeat'));
  assert.deepEqual(again, report);
  for (const family of families) {
    const subcases = report.cases.filter(c => c.family === family);
    assert.equal(subcases.length, 2);
    for (const c of subcases) {
      assert.equal(c.equal, !baseline);
      const check = baseline ? assert.notEqual : assert.equal;
      check(c.python.utf8_hex, c.worker.utf8_hex);
      check(c.python.value_key, c.worker.value_key);
    }
  }
});
test('A4 corrupt returned hash/bytes and wrong source/case identities fail closed', () => {
  const python = load(path.join(directory, 'positive/python-producer.stdout'));
  const worker = load(path.join(directory, 'positive/worker-producer.stdout'));
  const corruptHash = structuredClone(worker);
  corruptHash.rows[0].value_key = '0000000000000000';
  assert.throws(() => evaluate(corpus, python, corruptHash), /VALUE_KEY_INTEGRITY:ordinary_fraction/);
  const corruptBytes = structuredClone(worker);
  corruptBytes.rows[0].utf8_hex = '00';
  assert.throws(() => evaluate(corpus, python, corruptBytes), /BYTE_INTEGRITY:ordinary_fraction/);
  const wrongSource = structuredClone(worker);
  wrongSource.source_sha256 = '0'.repeat(64);
  assert.throws(() => evaluate(corpus, python, wrongSource), /PRODUCER_IDENTITY_MISMATCH/);
  const missingCase = structuredClone(worker);
  missingCase.rows.pop();
  assert.throws(() => evaluate(corpus, python, missingCase), /PRODUCER_CASE_SET_MISMATCH/);
  const counterfactual = structuredClone(python);
  const exponent = counterfactual.rows.find(row => row.id === 'exponent');
  if (baseline) {
    Object.assign(exponent, worker.rows.find(row => row.id === 'exponent'));
    assert.throws(() => evaluate(corpus, counterfactual, worker), /UNEXPECTED_AGREEMENT/);
  } else {
    // The original mismatch is internally valid evidence, but no longer acceptable.
    Object.assign(exponent, {text: '1e-05', utf8_hex: '31652d3035', value_key: '5a9530d3c6d5faad'});
    assert.throws(() => evaluate(corpus, counterfactual, worker), /PARITY_MISMATCH:exponent_parity:exponent/);
  }
  // Healthy complete control remains valid after every synthetic mutation.
  assert.equal(evaluate(corpus, python, worker).status, baseline ? 'PARITY_UNRESOLVED' : 'PARITY_RESOLVED');
});
for (const negative of ['corrupt-fixture', 'missing-runtime']) {
  test(`A4 strict diagnostic rejects ${negative} as unexpected, not expected red`, () => {
    const out = path.join(directory, negative);
    mkdirSync(out);
    let input = fixture;
    let runtime = python;
    if (negative === 'corrupt-fixture') {
      input = path.join(out, 'corrupt.json');
      writeFileSync(input, JSON.stringify({...corpus, provenance: 'synthetically corrupted'}));
    } else runtime = path.join(out, 'missing-python');
    const output = path.join(out, 'strict-negative');
    const strictArgs = baseline
      ? [process.execPath, path.join(HERE, 'diagnostic.mjs'), '--output', output, '--fixture', input, '--python', runtime]
      : [process.execPath, import.meta.filename, '--successor', output, input, runtime];
    const strict = child(strictArgs, out, 'strict-negative');
    assert.equal(strict.receipt.exit, 2);
    const message = JSON.parse(strict.stderr);
    assert.equal(message.status, 'UNEXPECTED_ERROR');
    assert.match(message.error, negative === 'corrupt-fixture' ? /FIXTURE_HASH_MISMATCH/ : /PYTHON_RUNTIME_FAILURE:ENOENT/);
  });
}
test('offline sentinels precede Python bound defaults and Worker imports', () => {
  const p = child([python, path.join(HERE, 'python_entry.py'), 'guard-probe', '--output', path.join(directory, 'guards')], directory, 'python-guards');
  assert.equal(p.receipt.exit, 0, p.stderr);
  assert.deepEqual(JSON.parse(p.stdout), {checks: 4, passed: 4, skipped: 0});
  const w = child([process.execPath, path.join(HERE, 'guard_probe.mjs')], directory, 'worker-guards');
  assert.equal(w.receipt.exit, 0, w.stderr);
  assert.deepEqual(JSON.parse(w.stdout), {checks: 5, passed: 5, skipped: 0});
});
