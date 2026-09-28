#!/usr/bin/env node
// Query SkipperCast forecast tiles with an Open-Meteo-style query string.
//   node scripts/model_api.mjs <tiles-root> forecast "latitude=35.3&longitude=-121&models=gfs_global&hourly=wind_speed_10m"
//   node scripts/model_api.mjs <tiles-root> meta gfs_global
// The Python pipeline calls this so it samples exactly as the Worker does.
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {answer, meta, QueryError} from '../server/model-api.js';

const [root, kind, query] = process.argv.slice(2);
if (!root || !kind) {
  console.error('usage: model_api.mjs <tiles-root> <forecast|marine|meta> <query|model>');
  process.exit(2);
}
const readJSON = async path => { try { return JSON.parse(await readFile(path, 'utf8')); } catch (e) { if (e.code === 'ENOENT') return null; throw e; } };
const store = {manifest: m => readJSON(join(root, m, 'manifest.json')), tile: (m, key) => readJSON(join(root, m, 'tiles', `${key}.json`))};
try {
  const now = process.env.SKIPPERCAST_NOW ? Number(process.env.SKIPPERCAST_NOW) : undefined;
  const result = kind === 'meta' ? await meta(query, store) : await answer(kind, new URLSearchParams(query), store, now);
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stdout.write(JSON.stringify({error: true, reason: error.message}));
  process.exit(error instanceof QueryError ? 3 : 1);
}
