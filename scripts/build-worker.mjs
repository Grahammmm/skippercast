import {build} from 'esbuild';
import {readdir,readFile,writeFile,mkdir,cp,rm} from 'node:fs/promises';
import {headersFile} from '../server/security-headers.js';
import {fingerprint} from './fingerprint.mjs';

const regions={};const draftRegions=[];
for(const id of await readdir('regions')){const region=JSON.parse(await readFile(`regions/${id}/region.json`,'utf8'));if(region.status==='draft')draftRegions.push(region);else regions[id]=region;}
const deployment=JSON.parse(await readFile('deployments/production.json','utf8'));
await rm('dist/client',{recursive:true,force:true});await mkdir('dist/client',{recursive:true});
// Dot-entries (editor or tool state) are never published.
for(const entry of await readdir('dist'))if(!['client','server'].includes(entry)&&!entry.startsWith('.'))await cp(`dist/${entry}`,`dist/client/${entry}`,{recursive:true});
const publicRules=new Set(Object.values(regions).map(region=>region.assets.regulations));
for(const region of draftRegions){const asset=region.assets.regulations;if(asset&&!publicRules.has(asset))await rm(`dist/client/${asset}`,{force:true});}

// Content-addressed front end. Browsers and edge caches can keep an old asset at
// a stable URL after a deploy, so every top-level script, stylesheet and page
// is renamed with the build's content hash and every reference is rewritten.
// Pages are served by the Worker (no-store) from the stable paths below.
const {buildId,shells}=await fingerprint('dist/client');
// Cloudflare applies these to static assets it serves without running the Worker.
await writeFile('dist/client/_headers',headersFile());

await build({entryPoints:['server/worker.js'],outfile:'dist/server/index.js',bundle:true,format:'esm',platform:'browser',target:'es2022',
  define:{REGIONS:JSON.stringify(regions),DEPLOYMENT:JSON.stringify(deployment),SHELLS:JSON.stringify(shells),BUILD_ID:JSON.stringify(buildId)},sourcemap:false});
console.log(`Built shared regional Worker and public assets (build ${buildId}).`);

// Offline shell (P4-08): dist/client/precache.json lists this build's
// fingerprinted assets for the service worker, and sw.js carries the build id
// so each deploy installs a new worker. Kept as one appended block.
const {writePrecache}=await import('./precache.mjs');
await writePrecache('dist/client',buildId);
