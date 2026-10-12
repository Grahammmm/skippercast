import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, existsSync} from 'node:fs';

const dist = new URL('../dist/', import.meta.url);
const read = name => readFileSync(new URL(name, dist), 'utf8');

test('consumer copy does not name the owner boat', () => {
  for (const name of readdirSync(dist).filter(n => n.endsWith('.js') && n !== 'region-default.js')) {
    assert.doesNotMatch(read(name), /parker/i, name);
  }
});

test('manifest is installable with PNG and maskable icons and one theme colour', () => {
  const manifest = JSON.parse(read('manifest.webmanifest'));
  assert.equal(manifest.id, '/');
  assert.equal(manifest.display, 'standalone');
  assert.match(manifest.theme_color, /^#[0-9a-f]{6}$/i);
  for (const size of ['192x192', '512x512']) {
    assert.ok(manifest.icons.some(i => i.sizes === size && i.type === 'image/png' && i.purpose === 'any'), size);
  }
  assert.ok(manifest.icons.some(i => i.purpose === 'maskable' && i.sizes === '512x512'));
  for (const icon of manifest.icons) assert.ok(existsSync(new URL(icon.src.slice(1), dist)), icon.src);
  const png = readFileSync(new URL('apple-touch-icon.png', dist));
  assert.equal(png.readUInt32BE(16), 180);
});
