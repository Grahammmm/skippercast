import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, delimiter, join } from 'node:path';
import { test } from 'node:test';

const build = '20000101';
const archive = `ca-coast-${build}.pmtiles`;
const artifacts = [archive, 'manifest.json', 'plan.json', 'detail.geojson'];
const steps = ['overview', 'detail', 'merge', 'verify'];
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');

// Exercise the real wrapper, detail check and manifest writer. Stub the listing
// and tile CLI only: a failed same-date retry must not change the prior output,
// even when an upstream command leaves a partial file before exiting.
for (const failure of [...steps, 'none']) {
  test(`same-build retry: ${failure === 'none' ? 'installs verified archive' : `preserves prior build on ${failure} failure`}`, (t) => {
    const root = mkdtempSync(join(tmpdir(), 'basemap-retry-'));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    const scripts = join(root, 'scripts', 'basemap');
    mkdirSync(scripts, { recursive: true });
    for (const file of ['build_basemap.sh', 'regions.py', 'check_detail.py']) {
      copyFileSync(new URL(`../scripts/basemap/${file}`, import.meta.url), join(scripts, file));
    }
    mkdirSync(join(root, 'regions', 'synthetic'), { recursive: true });
    writeFileSync(join(root, 'regions', 'synthetic', 'region.json'), JSON.stringify({
      id: 'synthetic', status: 'active', bounds: [0, 0, 1, 1],
    }));
    writeFileSync(join(root, 'python'), `#!/usr/bin/env python3
import sys
from pathlib import Path
script = Path(sys.argv.pop(1))
sys.path.insert(0, str(script.parents[2]))
from scripts.basemap import check_detail, regions
if script.name == 'check_detail.py':
    check_detail.main()
else:
    assert script.name == 'regions.py' and sys.argv[1] in ('plan', 'manifest')
    regions.listing = lambda: [{'key': '${build}.pmtiles', 'version': 'synthetic'}]
    regions.main()
`, { mode: 0o700 });
    const pmtiles = join(root, 'pmtiles');
    writeFileSync(pmtiles, `#!/usr/bin/env python3
import os
from pathlib import Path
import sys
command, *args = sys.argv[1:]
if command == 'extract':
    output = Path(args[1])
    step = 'overview' if args[2].startswith('--bbox=') else 'detail'
    if step == 'detail':
        assert Path(args[2].removeprefix('--region=')).is_file()
    output.write_bytes(step.encode() * 256)
elif command == 'merge':
    step = command
    Path(args[2]).write_bytes(Path(args[0]).read_bytes() + Path(args[1]).read_bytes() + os.environ['RETRY'].encode())
else:
    assert command == 'verify'
    step = command
    assert Path(args[0]).read_bytes() == b'overview' * 256 + b'detail' * 256 + os.environ['RETRY'].encode()
print(step)
if step == os.environ['FAIL_AT']:
    sys.exit(41)
`, { mode: 0o700 });
    const out = join(root, 'build output');
    const run = (failAt, retry) => spawnSync('bash', [join(scripts, 'build_basemap.sh'), build, basename(out)], {
      cwd: root, encoding: 'utf8', timeout: 10_000,
      env: { ...process.env, PATH: `${root}${delimiter}${process.env.PATH}`, PMTILES: pmtiles, FAIL_AT: failAt, RETRY: retry },
    });
    const snapshot = () => artifacts.map((file) => readFileSync(join(out, file)));
    const assertManifest = ([bytes, manifest]) => {
      const { sha256, key, bytes: size, source } = JSON.parse(manifest);
      assert.equal(sha256, digest(bytes));
      assert.equal(key, `tiles/basemap/ca-coast-${build}-${sha256.slice(0, 16)}.pmtiles`);
      assert.equal(size, bytes.length);
      assert.equal(source.build, build);
    };
    const first = run('none', 'original');
    assert.equal(first.status, 0, first.error?.message ?? first.stderr);
    const old = snapshot();
    assertManifest(old);

    const retry = run(failure, 'retry');
    assert.equal(retry.status, failure === 'none' ? 0 : 41, retry.error?.message ?? retry.stderr);
    assert.deepEqual(retry.stdout.split('\n').filter((line) => steps.includes(line)),
      failure === 'none' ? steps : steps.slice(0, steps.indexOf(failure) + 1));
    assert.ok(readdirSync(out).includes(archive), 'the prior local archive must still exist');
    const current = snapshot();
    assertManifest(current);
    if (failure === 'none') {
      assert.equal(current[0].subarray(-5).toString(), 'retry');
      assert.notEqual(digest(current[0]), digest(old[0]));
    } else {
      assert.deepEqual(current, old, 'failed retry must leave prior files byte-identical');
    }
    assert.deepEqual(readdirSync(out).sort(), [...artifacts].sort());
  });
}
