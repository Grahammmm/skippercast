import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, existsSync} from 'node:fs';

const dist = new URL('../dist/', import.meta.url);
const read = name => readFileSync(new URL(name, dist), 'utf8');
const html = read('index.html');

function staticImports(name) {
  const text = read(name);
  return [...text.matchAll(/^\s*import\s[^;]*?from\s*["']\.\/([^"']+)["']/gm), ...text.matchAll(/^import\s*["']\.\/([^"']+)["']/gm)].map(m => m[1]);
}

test('modulepreload covers the boot chain and the app.js static graph exactly', () => {
  // coastal-discovery.js is only imported for ?coast= pages, so it is not preloaded.
  const roots = [...read('boot.js').matchAll(/import\(\s*["']\.\/([^"']+)["']/g)].map(m => m[1]).filter(n => n !== 'coastal-discovery.js');
  assert.ok(roots.includes('app.js') && roots.includes('home-port.js'));
  const seen = new Set();
  const walk = name => { if (seen.has(name)) return; seen.add(name); staticImports(name).forEach(walk); };
  roots.forEach(walk);
  const preloads = [...html.matchAll(/<link rel="modulepreload" href="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(preloads).size, preloads.length, 'duplicate modulepreload');
  assert.deepEqual([...preloads].sort(), [...seen].sort());
});

test('boat heading input is bound once, not on every forecast render', () => {
  const source = read('weather-ui.js');
  const render = source.slice(source.indexOf('function render()'), source.indexOf('async function loadLive()'));
  assert.ok(render.length > 100, 'render() not found');
  assert.doesNotMatch(render, /boat-heading/);
  assert.doesNotMatch(render, /addEventListener/);
  assert.match(source, /\$\("marine-detail-body"\)\.addEventListener\("input"/);
});

test('consumer copy does not name the owner boat', () => {
  for (const name of readdirSync(dist).filter(n => n.endsWith('.js') && n !== 'region-default.js')) {
    assert.doesNotMatch(read(name), /parker/i, name);
  }
});

test('boot failure shows a friendly message with retry, not the raw error', () => {
  const failure = read('boot.js').split('catch(error)')[1];
  assert.doesNotMatch(failure, /error\.message/);
  assert.match(failure, /location\.reload\(\)/);
  assert.match(failure, /console\.error/);
});

test('manifest is installable with PNG and maskable icons and one theme colour', () => {
  const manifest = JSON.parse(read('manifest.webmanifest'));
  assert.equal(manifest.id, '/');
  assert.equal(manifest.display, 'standalone');
  const themes = [...html.matchAll(/<meta name="theme-color" content="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(themes, [manifest.theme_color]);
  for (const size of ['192x192', '512x512']) {
    assert.ok(manifest.icons.some(i => i.sizes === size && i.type === 'image/png' && i.purpose === 'any'), size);
  }
  assert.ok(manifest.icons.some(i => i.purpose === 'maskable' && i.sizes === '512x512'));
  for (const icon of manifest.icons) assert.ok(existsSync(new URL(icon.src.slice(1), dist)), icon.src);
  assert.match(html, /<link rel="apple-touch-icon" href="apple-touch-icon\.png"\/>/);
  const png = readFileSync(new URL('apple-touch-icon.png', dist));
  assert.equal(png.readUInt32BE(16), 180);
});
