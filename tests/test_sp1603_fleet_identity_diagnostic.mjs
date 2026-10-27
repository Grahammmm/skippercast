// A1-A4 characterization: success means truthful red evidence, NOT parity.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, writeFileSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {collect, evaluate, child, load, discoveryPython, HERE, ROOT, families} from './fixtures/sp1603_fleet_identity_diagnostic/diagnostic.mjs';

const directory = mkdtempSync(path.join(process.env.SP1603_OUTPUT ?? tmpdir(), 'sp1603-characterization-'));
const corpus = load(path.join(HERE, 'corpus.json'));
const python = discoveryPython();
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
test('A1 exact two unresolved root IDs and measured exponent/control values', () => {
  assert.equal(report.status, 'PARITY_UNRESOLVED');
  assert.equal(report.strict_exit, 1);
  assert.deepEqual(report.mismatch_ids, families);
  assert.deepEqual(report.counts, {root_tests: 2, passed: 0, failed: 2, controls: 13, cases: 17, skipped: 0});
  const exponent = report.cases.find(c => c.id === 'exponent');
  assert.equal(exponent.python.value_key, '5a9530d3c6d5faad');
  assert.equal(exponent.worker.value_key, '661710915adfa7c4');
  assert.equal(report.cases.find(c => c.id === 'ordinary_fraction').worker.value_key, '9f29a130438b8117');
  const astral = report.cases.find(c => c.id === 'astral_keys');
  assert.equal(astral.python.text, '{"\ue000":1,"\u{10000}":2}');
  assert.equal(astral.worker.text, '{"\u{10000}":2,"\ue000":1}');
});
test('A3 nested evidence and actual bytes/keys deterministic across fresh producer processes', () => {
  const again = collect(path.join(directory, 'repeat'));
  assert.deepEqual(again, report);
  for (const family of families) {
    const subcases = report.cases.filter(c => c.family === family);
    assert.equal(subcases.length, 2);
    for (const c of subcases) {
      assert.equal(c.equal, false);
      assert.notEqual(c.python.utf8_hex, c.worker.utf8_hex);
      assert.notEqual(c.python.value_key, c.worker.value_key);
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
  const agree = structuredClone(worker);
  agree.rows[13] = structuredClone(python.rows[13]);
  assert.throws(() => evaluate(corpus, python, agree), /UNEXPECTED_AGREEMENT/);
  // Healthy complete control remains valid after every synthetic mutation.
  assert.equal(evaluate(corpus, python, worker).status, 'PARITY_UNRESOLVED');
});
for (const negative of ['corrupt-fixture', 'missing-runtime']) {
  test(`A4 actual acceptance wrapper rejects ${negative} as unexpected, not expected red`, () => {
    const out = path.join(directory, negative);
    mkdirSync(out);
    const args = [python, path.join(ROOT, 'scripts/accept_sp1603_fleet_identity_diagnostic.py'),
      '--suite', 'baseline', '--output', out];
    if (negative === 'corrupt-fixture') {
      const bad = path.join(out, 'corrupt.json');
      writeFileSync(bad, JSON.stringify({...corpus, provenance: 'synthetically corrupted'}));
      args.push('--fixture', bad);
    } else args.push('--python', path.join(out, 'missing-python'));
    const result = child(args, out, 'acceptance-negative');
    assert.equal(result.receipt.exit, 1, result.stderr);
    const summary = JSON.parse(result.stdout);
    assert.equal(summary.status, 'UNEXPECTED_ERROR');
    assert.equal(summary.error, negative === 'corrupt-fixture' ? 'FIXTURE_HASH_MISMATCH' : 'PYTHON_RUNTIME_MISSING');
    assert.equal(load(path.join(summary.output, 'acceptance.json')).children.length, 0, 'outer wrapper rejects before any child launch');
    const strictArgs = [process.execPath, path.join(HERE, 'diagnostic.mjs'), '--output', path.join(out, 'strict-negative')];
    strictArgs.push(...args.slice(6)); // exactly the same synthetic override
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
