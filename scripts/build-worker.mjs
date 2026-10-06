import {build} from 'esbuild';
import {existsSync} from 'node:fs';
import {readdir,readFile,rm} from 'node:fs/promises';
import {headersFile} from '../server/security-headers.ts';
import {buildClient,advisorAssetPaths} from './client-build.mjs';

const regions={};const draftRegions=[];
// Coastal regions only: state-level fleet directories (regions/CA/fleet.json) hold no region.json.
for(const id of await readdir('regions')){if(!existsSync(`regions/${id}/region.json`))continue;const region=JSON.parse(await readFile(`regions/${id}/region.json`,'utf8'));if(region.status==='draft')draftRegions.push(region);else regions[id]=region;}
const deployment=JSON.parse(await readFile('deployments/production.json','utf8'));
// Content-addressed front end (P4-01a): Vite bundles the pages, modules and
// stylesheets into hashed assets; scripts/client-build.mjs copies the static
// data, renames pages NAME.<buildId>.html and writes precache.json, the stamped
// sw.js, _headers and .assetsignore. Pages are served by the Worker (no-store)
// from their stable paths via SHELLS.
const {buildId,shells,manifest}=await buildClient({root:'dist',out:'dist/client',headers:headersFile()});
// FE-01: the front-end rebuild's shells (dist/landing.html at /, dist/app.html at /map) are
// served only behind UI_V2 (server/routes/assets.ts); a build without them would answer the
// switch with a bare 404, so their absence fails the build here.
for(const page of ['/landing.html','/app.html'])if(!shells[page])throw Error(`dist${page} is missing from the built pages (SHELLS)`);
// TA-W1: the server-rendered advisor pages link dist/chat.html's hashed stylesheet set (tokens, the chat
// island's and advisor/pages.css) and its entry script (the chat island and the pages' telemetry).
const advisorAssets=advisorAssetPaths(manifest);
const publicRules=new Set(Object.values(regions).map(region=>region.assets.regulations));
for(const region of draftRegions){const asset=region.assets.regulations;if(asset&&!publicRules.has(asset))await rm(`dist/client/${asset}`,{force:true});}

await build({entryPoints:['server/index.ts'],outfile:'dist/server/index.js',bundle:true,format:'esm',platform:'browser',target:'es2022',
  define:{REGIONS:JSON.stringify(regions),DEPLOYMENT:JSON.stringify(deployment),SHELLS:JSON.stringify(shells),BUILD_ID:JSON.stringify(buildId),ADVISOR_ASSETS:JSON.stringify(advisorAssets)},sourcemap:false});
console.log(`Built shared regional Worker and public assets (build ${buildId}).`);

