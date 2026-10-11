// Vite build for the static client (P4-01a).
//
// The authored pages, modules and stylesheets stay in dist/ for now (the Node
// tests import dist/*.js directly); Vite reads them from there and writes the
// hashed site to dist/client. scripts/build-worker.mjs runs this build, then
// copies the static data (data/, regions/, vendor/, downloads/, tiles/, icons,
// the web manifest and sw.js) unchanged and reads .vite/manifest.json to
// produce the Worker's page map, precache.json, _headers and the stamped sw.js.
//
// Vendored libraries (dist/vendor, SHA-pinned in scripts/web-vendor-sha256.json
// with SRI attributes in the pages) are not bundled: the staticRefs plugin
// marks their tags vite-ignore, so they stay at their stable /vendor/ paths
// with their integrity attributes intact. The web manifest and icons keep
// their stable URLs the same way (the manifest names its icons by path).
import {readdirSync} from 'node:fs';
import {basename, resolve} from 'node:path';
import {defineConfig} from 'vite';

/** Every page (NAME.html) directly in `root` is an entry. */
export const pages = root => readdirSync(root).filter(name => name.endsWith('.html')).sort();

// name.<10 hex>.ext: the fingerprint shape sw.js treats as immutable and
// scripts/check_client.mjs requires.
const output = {
  entryFileNames: 'assets/[name].[hash:10].js',
  chunkFileNames: 'assets/[name].[hash:10].js',
  assetFileNames: 'assets/[name].[hash:10][extname]',
  hashCharacters: 'hex',
  // FE-61: MapLibre GL and PMTiles get a chunk of their own. Without the v1
  // pages' shared chunks, Rolldown put its runtime helpers in the MapLibre
  // chunk (the libraries are CommonJS), so the app's and the landing's first
  // paint statically imported MapLibre (about 290 KB gzipped).
  codeSplitting: {groups: [{name: 'maplibre-gl', test: /[\\/]node_modules[\\/].*(?:maplibre-gl|pmtiles)[\\/]/}]},
};

// Tags Vite must leave alone: vendor/ files, the web manifest and image icons.
export const STATIC_REF = /<(script|link)\b(?=[^>]*\s(?:src|href)="(?:vendor\/|manifest\.webmanifest"|[\w-]+\.(?:png|svg|jpg)"))/g;

/** Leave static-file <script>/<link> tags to the browser, SRI and all. */
function staticRefs() {
  return {
    name: 'skippercast:static-refs',
    transformIndexHtml: {order: 'pre', handler: html => html.replace(STATIC_REF, '<$1 vite-ignore')},
  };
}

// One stylesheet per page, in document order. Pages share tokens.css and
// styles.css; left as separate links, Vite would split the shared sheets into
// a common chunk and emit it after the page's own sheet, reversing the
// cascade. Instead each page's local <link rel="stylesheet"> tags become one
// generated NAME.page.css that @imports them in their original order, so the
// built page loads a single stylesheet with the authored cascade.
export const PAGE_STYLESHEET = /<link rel="stylesheet" href="([\w.-]+\.css)"\s*\/?>[ \t]*\n?/g;

function pageStyles(root) {
  const sheets = new Map();
  return {
    name: 'skippercast:page-styles',
    enforce: 'pre',
    transformIndexHtml: {
      order: 'pre',
      handler(html, ctx) {
        const list = [];
        html = html.replace(PAGE_STYLESHEET, (_, href) => { list.push(href); return ''; });
        if (!list.length) return html;
        const name = `${basename(ctx.filename, '.html')}.page.css`;
        sheets.set(name, list);
        return html.replace('</head>', `<link rel="stylesheet" href="${name}">\n</head>`);
      },
    },
    resolveId(id) {
      const name = basename(id.split('?')[0]);
      return sheets.has(name) ? resolve(root, name) : null;
    },
    load(id) {
      const name = basename(id);
      if (id === resolve(root, name) && sheets.has(name)) return sheets.get(name).map(href => `@import "./${href}";`).join('\n') + '\n';
      return null;
    },
  };
}

/** The client build for authored pages in `root`, written to `outDir`. */
export function clientConfig({root = resolve(import.meta.dirname, 'dist'), outDir = resolve(root, 'client')} = {}) {
  return {
    root,
    base: './',
    publicDir: false,
    logLevel: 'warn',
    plugins: [staticRefs(), pageStyles(root)],
    // Preact islands in web/ (P4-01b): JSX compiles to preact/jsx-runtime.
    oxc: {jsx: {runtime: 'automatic', importSource: 'preact'}},
    build: {
      outDir,
      emptyOutDir: true,
      manifest: true,
      // Every supported browser has native modulepreload; skip the polyfill.
      modulePreload: {polyfill: false},
      // FE-61: minified. It stayed off while the v1 shell's ~20 sheets were
      // built: merging their repeated selectors dropped a later !important
      // override and changed the page.
      cssMinify: true,
      // No data: URLs for small files: every asset stays a hashed file.
      assetsInlineLimit: 0,
      sourcemap: false,
      reportCompressedSize: false,
      rolldownOptions: {
        input: Object.fromEntries(pages(root).map(name => [name.replace(/\.html$/, ''), resolve(root, name)])),
        output,
      },
    },
    worker: {format: 'es', rolldownOptions: {output}},
  };
}

export default defineConfig(clientConfig());
