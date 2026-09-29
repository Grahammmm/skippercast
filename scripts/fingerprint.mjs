// Fingerprint a static client directory in place.
//
// Every top-level .js/.css/.html file is renamed NAME.<buildId>.EXT and every
// reference to it (import specifiers, new URL(...), src/href attributes) in those
// files is rewritten. The build id hashes all of their authored contents, so any
// change produces new URLs and nothing stale can be served from an edge cache.
// STABLE files are left in place, unrenamed, and excluded from the hash.
// Returns {buildId, shells}: shells maps stable page paths ('/', '/sources.html')
// to their fingerprinted files for the Worker to serve with no-store.
import {createHash} from 'node:crypto';
import {readdir, readFile, writeFile, rm} from 'node:fs/promises';
import {join} from 'node:path';

const ASSET = /\.(?:js|css|html)$/;
// Files that must keep their URL. A service worker's script URL is its identity:
// renaming it registers a different worker, and the page registers '/sw.js'.
// The Worker serves these with Cache-Control: no-cache so updates still land.
export const STABLE = new Set(['sw.js']);

export function hashName(name, buildId) {
  const dot = name.lastIndexOf('.');
  return `${name.slice(0, dot)}.${buildId}${name.slice(dot)}`;
}

// Replace references to known top-level assets. A reference is the bare or
// ./-prefixed file name directly inside quotes, backticks or parentheses,
// optionally followed by a legacy ?v= query, which is dropped.
export function rewrite(text, names, buildId) {
  return text.replace(/(["'`(])(\.\/)?([A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:js|css|html))(\?v=[0-9A-Za-z._-]+)?(?=["'`)#])/g,
    (match, open, dot, name) => (names.has(name) ? `${open}${dot || ''}${hashName(name, buildId)}` : match));
}

export async function fingerprint(dir) {
  const names = (await readdir(dir, {withFileTypes: true})).filter(e => e.isFile() && ASSET.test(e.name) && !STABLE.has(e.name)).map(e => e.name).sort();
  const contents = new Map();
  const hash = createHash('sha256');
  for (const name of names) {
    const text = await readFile(join(dir, name), 'utf8');
    contents.set(name, text);
    hash.update(name).update('\0').update(text).update('\0');
  }
  const buildId = hash.digest('hex').slice(0, 10);
  const set = new Set(names);
  for (const name of names) {
    await writeFile(join(dir, hashName(name, buildId)), rewrite(contents.get(name), set, buildId));
    await rm(join(dir, name));
  }
  const shells = {};
  for (const name of names.filter(n => n.endsWith('.html'))) {
    shells[`/${name}`] = `/${hashName(name, buildId)}`;
    if (name === 'index.html') shells['/'] = shells['/index.html'];
  }
  return {buildId, shells};
}
