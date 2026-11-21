import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {CHART_FILE_NAMES, chartFileListed, chartFilesOf, publishedChartFiles} from '../web/chart-files.ts';

const region = 'fixture-region';
const sideFiles = ['poster.svg', 'shoreline.geojson', 'land-water.json'];

test.afterEach(() => { publishedChartFiles.value = null; });

// Checking only that entries are strings leaves a malformed list suppressing real files.
for (const [defect, raw] of [
  ['an unknown name', ['poster.svg', 'shoreline.geosjon']],
  ['a duplicate name', ['poster.svg', 'poster.svg']]
]) {
  test(`a chart_files list with ${defect} fails open`, () => {
    const files = chartFilesOf(raw);
    assert.equal(files, null);
    publishedChartFiles.value = {region, files};
    for (const name of sideFiles) assert.equal(chartFileListed(region, name), true, name);
  });
}

// Don't trade the malformed-list fix for a fallback that ignores valid omissions.
test('valid partial and empty chart_files lists still suppress omitted files', () => {
  for (const raw of [['poster.svg'], []]) {
    const files = chartFilesOf(raw);
    assert.deepEqual(files, raw);
    publishedChartFiles.value = {region, files};
    for (const name of sideFiles) assert.equal(chartFileListed(region, name), raw.includes(name), name);
  }
});

// A filename added or removed only on one side changes which manifests can suppress requests.
test('the chart_files allowlist matches the region schema enum', () => {
  const schema = JSON.parse(readFileSync(new URL('../schemas/region.schema.json', import.meta.url), 'utf8'));
  const names = schema.properties.chart_files.items.enum;
  assert.deepEqual([...CHART_FILE_NAMES].sort(), [...names].sort());
  assert.deepEqual(chartFilesOf(names), names);
});
