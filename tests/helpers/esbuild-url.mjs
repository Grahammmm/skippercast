// Shared esbuild plugin for tests that bundle web/ modules for rendering.
// The terrain and MapLibre modules are dynamic imports that rendering never reaches, so they stay external.
// Vite `?url` asset imports (stylesheets, fonts) bundle as their path, standing in for Vite's hashed URL.
import {readFile} from 'node:fs/promises';

const rendererSetup = (b, {stubStylesheets}) => {
  b.onResolve({filter: /^\.\/(?:map\/)?(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}));
  if (stubStylesheets) {
    // Side-effect stylesheet imports (web/brief/Brief.tsx's print sheet, reached through the planner's shared forecast loader) are not rendered markup.
    b.onResolve({filter: /\.css$/}, args => ({path: args.path, namespace: 'empty-css'}));
    b.onLoad({filter: /.*/, namespace: 'empty-css'}, () => ({contents: '', loader: 'js'}));
  }
  b.onResolve({filter: /\?url$/}, args => ({path: args.path, namespace: 'url'}));
  b.onLoad({filter: /.*/, namespace: 'url'}, args => ({contents: `export default ${JSON.stringify(args.path)};`, loader: 'js'}));
};
export const rendererPlugin = {name: 'renderers', setup: b => rendererSetup(b, {stubStylesheets: true})};
// For a page-style bundle (write: false) that injects the stylesheets esbuild collects: the same renderers, with the CSS kept.
export const styledRendererPlugin = {name: 'renderers-styled', setup: b => rendererSetup(b, {stubStylesheets: false})};
export const rendererPlugins = [rendererPlugin];
export const styledRendererPlugins = [styledRendererPlugin];

// SC1407-09: opt-in for semantic suites that render Spanish synchronously. The bundled web/i18n-catalogue.ts
// awaits the real Spanish table before any module that imports it runs (top-level await, so esm bundles only),
// as the pages' startup does before their first render. Cold-load tests use rendererPlugins, the unmodified loader.
export const preparedCatalogue = {name: 'prepared-catalogue', setup: b => {
  b.onLoad({filter: /[\\/]web[\\/]i18n-catalogue\.ts$/}, async args => ({contents: `${await readFile(args.path, 'utf8')}\nawait prepareCatalogue('es');\n`, loader: 'ts'}));
}};
export const preparedRendererPlugins = [rendererPlugin, preparedCatalogue];
