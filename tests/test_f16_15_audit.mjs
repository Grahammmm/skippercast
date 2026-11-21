// F16-15: the whole handle name (not just the sheet name) follows the app language.
import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(new URL('../', import.meta.url)), contents: `
    export {Sheet} from './web/ui/Sheet.tsx';
    export {language, prepareCatalogue, t} from './web/i18n.ts';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';
  `},
  bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', jsxImportSource: 'preact',
});
const {Sheet, language, prepareCatalogue, t, h, render} = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);
await prepareCatalogue('es');

for (const [lang, expand, collapse] of [
  ['en', 'Expand Brief', 'Collapse Brief'],
  ['es', 'Expandir Resumen', 'Contraer Resumen'],
]) {
  for (const [detent, name, expanded] of [
    ['peek', expand, 'false'], ['half', expand, 'true'], ['full', collapse, 'true'],
  ]) {
    test(`${lang} ${detent}: handle has the full localized name and unchanged expanded state`, () => {
      language.value = lang;
      const label = t('shell.brief', lang);
      const html = render(h(Sheet, {label, detent, onDetent() {}}, 'Synthetic body'));
      const handle = html.match(/<button\b[^>]*>/)?.[0];
      assert.ok(handle, 'the sheet has a button');
      assert.equal(handle.match(/\baria-label="([^"]*)"/)?.[1], name);
      assert.equal(handle.match(/\baria-expanded="([^"]*)"/)?.[1], expanded);
    });
  }
}
