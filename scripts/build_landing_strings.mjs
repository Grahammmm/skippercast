// Generate the landing's first-paint slice from the one shared catalogue.
// The deferred live verdict continues to use the complete app reader.
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root = new URL('../', import.meta.url);
const catalog = JSON.parse(readFileSync(new URL('catalog/app/strings.json', root)));
const strings = Object.fromEntries(Object.entries(catalog.strings).filter(([id]) =>
  (id.startsWith('landing.') && !id.startsWith('landing.basis.') && !id.startsWith('landing.reading.') && id !== 'landing.place.from') || id.startsWith('where.profile.') || ['brief.planning', 'brief.terms', 'brief.disclaimer', 'tile.wind', 'tile.swell', 'tile.water', 'tile.tide'].includes(id)));
const path = new URL('web/landing/strings.generated.json', root);
const text = JSON.stringify(strings) + '\n';
if (process.argv.includes('--check')) {
  if (readFileSync(path, 'utf8') !== text) throw Error('Run node scripts/build_landing_strings.mjs');
} else writeFileSync(fileURLToPath(path), text);
