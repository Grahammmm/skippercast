#!/usr/bin/env node
// Write the deploy-time Wrangler config: wrangler.jsonc with the real D1 id and
// bucket names filled in. Usage:
//   node scripts/wrangler_config.mjs <d1-database-id> <feeds-bucket> [out]
// Comments are removed by a string-aware scanner, so "//" inside a value (the
// $schema path, a URL) is never mistaken for a comment.
import {readFileSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

export function stripJsonComments(text) {
  let out = '', i = 0, inString = false;
  while (i < text.length) {
    const c = text[i], next = text[i + 1];
    if (inString) {
      out += c;
      if (c === '\\') { out += next ?? ''; i += 2; continue; }
      if (c === '"') inString = false;
      i++;
    } else if (c === '"') { inString = true; out += c; i++; }
    else if (c === '/' && next === '/') { while (i < text.length && text[i] !== '\n') i++; }
    else if (c === '/' && next === '*') { const end = text.indexOf('*/', i + 2); if (end < 0) throw Error('unterminated block comment'); i = end + 2; }
    else { out += c; i++; }
  }
  return out.replace(/,(\s*[}\]])/g, '$1');   // tolerate trailing commas
}

export function deployConfig(text, databaseId, bucket) {
  if (!/^[0-9a-f-]{36}$/.test(databaseId)) throw Error(`not a D1 database id: ${databaseId}`);
  if (!/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(bucket)) throw Error(`not an R2 bucket name: ${bucket}`);
  const config = JSON.parse(stripJsonComments(text));
  config.d1_databases[0].database_id = databaseId;
  config.r2_buckets[0].bucket_name = bucket;
  return config;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [databaseId, bucket, out = 'wrangler.deploy.jsonc'] = process.argv.slice(2);
  const config = deployConfig(readFileSync('wrangler.jsonc', 'utf8'), databaseId || '', bucket || '');
  writeFileSync(out, JSON.stringify(config, null, 2) + '\n');
  console.log(`Wrote ${out}`);
}
