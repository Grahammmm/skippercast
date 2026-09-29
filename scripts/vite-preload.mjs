// Boot-chain modulepreload for the app shell (P4-01a).
//
// boot.js loads the app through a chain of awaited dynamic imports
// (home-port -> region -> coasts -> app ...). Vite preloads an entry's static
// imports and a dynamic import's dependencies at the moment it runs, but not
// the chain itself, so without help the browser discovers each step only when
// the previous one has executed. This plugin adds <link rel="modulepreload">
// for every chunk that boot.js imports on a normal start, plus their static
// imports, so the whole start graph downloads in parallel with the entry.
// It replaces the hand-maintained list that used to live in dist/index.html;
// scripts/check_client.mjs verifies the built page against .vite/manifest.json.
import {readFileSync} from 'node:fs';
import {join} from 'node:path';

// Imported only for ?coast= pages, so never preloaded on a normal start.
export const NOT_PRELOADED = new Set(['coastal-discovery.js']);

/** The ./module.js names boot.js imports dynamically on a normal start. */
export function bootPreloadRoots(source) {
  return [...new Set([...source.matchAll(/import\(\s*["']\.\/([^"']+)["']\s*\)/g)].map(m => m[1]))]
    .filter(name => !NOT_PRELOADED.has(name));
}

/** Chunk file names holding `roots` (module ids) and everything they import statically. */
export function preloadChunks(bundle, rootIds, exclude = new Set(), start = []) {
  const chunks = Object.values(bundle).filter(c => c.type === 'chunk');
  const out = [];
  const seen = new Set(exclude);
  const visit = chunk => {
    if (!chunk || seen.has(chunk.fileName)) return;
    seen.add(chunk.fileName);
    out.push(chunk.fileName);
    for (const file of chunk.imports) visit(bundle[file]);
  };
  for (const chunk of start) visit(chunk);
  // A dynamic import loads the module's facade chunk when it has one (a thin
  // re-export of a shared chunk), otherwise the chunk that contains it.
  for (const id of rootIds) visit(chunks.find(c => c.facadeModuleId === id) || chunks.find(c => c.moduleIds.includes(id)));
  return out;
}

/** Vite plugin: modulepreload the boot chain in `page` (default index.html). */
export function bootPreload({root, page = 'index.html', boot = 'boot.js'}) {
  return {
    name: 'skippercast:boot-preload',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        if (ctx.path !== `/${page}` || !ctx.bundle || !ctx.chunk) return html;
        const roots = bootPreloadRoots(readFileSync(join(root, boot), 'utf8')).map(name => join(root, name));
        // The entry and what Vite already preloads for it (its static graph) are skipped.
        const already = new Set(preloadChunks(ctx.bundle, [], new Set(), [ctx.chunk]));
        return preloadChunks(ctx.bundle, roots, already).map(file => ({
          tag: 'link', attrs: {rel: 'modulepreload', crossorigin: true, href: `./${file}`}, injectTo: 'head',
        }));
      },
    },
  };
}
