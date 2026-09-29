import {build} from 'esbuild';
import {readdir,readFile,rm} from 'node:fs/promises';
import {headersFile} from '../server/security-headers.ts';
import {buildClient} from './client-build.mjs';

const regions={};const draftRegions=[];
for(const id of await readdir('regions')){const region=JSON.parse(await readFile(`regions/${id}/region.json`,'utf8'));if(region.status==='draft')draftRegions.push(region);else regions[id]=region;}
const deployment=JSON.parse(await readFile('deployments/production.json','utf8'));
// Content-addressed front end (P4-01a): Vite bundles the pages, modules and
// stylesheets into hashed assets; scripts/client-build.mjs copies the static
// data, renames pages NAME.<buildId>.html and writes precache.json, the stamped
// sw.js, _headers and .assetsignore. Pages are served by the Worker (no-store)
// from their stable paths via SHELLS.
const {buildId,shells}=await buildClient({root:'dist',out:'dist/client',headers:headersFile()});
const publicRules=new Set(Object.values(regions).map(region=>region.assets.regulations));
for(const region of draftRegions){const asset=region.assets.regulations;if(asset&&!publicRules.has(asset))await rm(`dist/client/${asset}`,{force:true});}

await build({entryPoints:['server/index.ts'],outfile:'dist/server/index.js',bundle:true,format:'esm',platform:'browser',target:'es2022',
  define:{REGIONS:JSON.stringify(regions),DEPLOYMENT:JSON.stringify(deployment),SHELLS:JSON.stringify(shells),BUILD_ID:JSON.stringify(buildId)},sourcemap:false});
console.log(`Built shared regional Worker and public assets (build ${buildId}).`);

