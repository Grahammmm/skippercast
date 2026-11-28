import {basename} from 'node:path';

const expected = new Map([
  ['advisor-chat.spec.ts', 'the web chat opens, sends a message and shows the reply'],
  ['v2-conditions.spec.ts', 'BF-hourly-table: the hour-by-hour row follows the chart and the dock; a row (click or Enter) moves both'],
  ['v2-landing.spec.ts', '/map with no area opens the landing without a saved port, and the saved port with one'],
  ['v2-map.spec.ts', 'the Chart draws the basemap and the Morro Bay coastline with a Sources link and no credit text'],
]);

// Playwright can exit zero with a partial selection, skipped cases, or retry passes.
// Require one clean result for each named laptop test in the actual run instead.
export default class FastCheckReporter {
  onBegin(_config, suite) {
    this.tests = suite.allTests();
  }

  onEnd({status}) {
    if (status !== 'passed') return;
    const missing = new Map(expected);
    for (const test of this.tests) {
      const file = basename(test.location.file);
      const [result] = test.results;
      if (missing.get(file) !== test.title || test.parent.project()?.name !== 'laptop' ||
          test.expectedStatus !== 'passed' || test.results.length !== 1 || result.status !== 'passed') {
        console.error(`Fast check: unexpected test or outcome: ${file} › ${test.title}`);
        return {status: 'failed'};
      }
      missing.delete(file);
    }
    if (missing.size !== 0) {
      console.error(`Fast check: missing ${[...missing.keys()].join(', ')}`);
      return {status: 'failed'};
    }
    console.log(`Fast check: ${expected.size} expected laptop tests passed.`);
  }
}
