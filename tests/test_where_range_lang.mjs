import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {reachLabel} from '../web/map/reach.ts';
import {nmText} from '../web/reach.ts';

// A locale-only change must not add trailing zeros, alter rounding, or change the default map label.
test('C2: nmText keeps the English bytes and localizes only the Spanish distance', () => {
  for (const [nm, en, es] of [[12.5, '12.5 nm', '12,5 nm'], [12.0, '12 nm', '12 nm'], [0.25, '0.3 nm', '0,3 nm'], [12.35, '12.3 nm', '12,3 nm']]) {
    assert.equal(nmText(nm), en, `default ${nm}`);
    assert.equal(nmText(nm, 'en'), en, `English ${nm}`);
    assert.equal(nmText(nm, 'es'), es, `Spanish ${nm}`);
  }
  assert.equal(reachLabel(12.5, 'Morro Bay'), '12.5 nm from Morro Bay · straight line, not a route');
});

async function rangeButtonFixture() {
  const {outputFiles: [bundle]} = await build({
    stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {WhereToLook} from './web/brief/WhereToLook.tsx';
      export {language} from './web/i18n.ts';
      export {profile} from './web/state.ts';
      export {reachRange} from './web/reach.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', write: false, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
  });
  const m = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);
  const ranking = {source: null, picks: [], empty: 'No picks', harbor: 'Morro Bay'};
  m.profile.value = 'boat';
  return (lang, reachRange) => {
    m.language.value = lang;
    m.reachRange.value = reachRange;
    return m.render(m.h(m.WhereToLook, {ranking})).match(/<button\b[^>]*\bapp-where-range"[^>]*>[^<]*<\/button>/)?.[0];
  };
}

const buttonEnd = ' type="button" class="ui-button ui-button--ghost ui-button--sm app-where-range">';
let fixture;
const loadRangeButton = () => fixture ??= rangeButtonFixture();

// The formatter unit test cannot catch either template independently forgetting to forward lang.
test('C3: the Spanish range button localizes both its title and visible value', async () => {
  const button = await loadRangeButton();
  assert.equal(button('es', {boat: 12.5}), '<button aria-haspopup="dialog" data-reach="12.5" title="Alcance a considerar: 12,5 nm por agua donde haya un trayecto calculado; de lo contrario, en línea recta, desde Morro Bay"' + buttonEnd + 'Alcance 12,5 nm</button>');
  assert.equal(button('es', {}), '<button aria-haspopup="dialog" title="Define hasta dónde buscar"' + buttonEnd + 'Definir alcance</button>');
});

test('C4: the English range button retains its exact markup with and without a fractional reach', async () => {
  const button = await loadRangeButton();
  assert.equal(button('en', {boat: 12.5}), '<button aria-haspopup="dialog" data-reach="12.5" title="Range to consider: 12.5 nm by water where routed, else straight line, from Morro Bay"' + buttonEnd + 'Range 12.5 nm</button>');
  assert.equal(button('en', {}), '<button aria-haspopup="dialog" title="Set how far out to look"' + buttonEnd + 'Set range</button>');
});
