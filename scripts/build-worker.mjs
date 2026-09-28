import {build} from 'esbuild';
import {readdir,readFile,mkdir,cp,rm} from 'node:fs/promises';
import {fingerprint} from './fingerprint.mjs';

const regions={};const draftRegions=[];
for(const id of await readdir('regions')){const region=JSON.parse(await readFile(`regions/${id}/region.json`,'utf8'));if(region.status==='draft')draftRegions.push(region);else regions[id]=region;}
const deployment=JSON.parse(await readFile('deployments/production.json','utf8'));
await rm('dist/client',{recursive:true,force:true});await mkdir('dist/client',{recursive:true});
for(const entry of await readdir('dist'))if(!['client','server','.openai'].includes(entry))await cp(`dist/${entry}`,`dist/client/${entry}`,{recursive:true});
const publicRules=new Set(Object.values(regions).map(region=>region.assets.regulations));
for(const region of draftRegions){const asset=region.assets.regulations;if(asset&&!publicRules.has(asset))await rm(`dist/client/${asset}`,{force:true});}

// Content-addressed front end. The Sites edge can keep serving an old asset at
// a stable URL after a deploy, so every top-level script, stylesheet and page
// is renamed with the build's content hash and every reference is rewritten.
// Pages are served by the Worker (no-store) from the stable paths below.
const {buildId,shells}=await fingerprint('dist/client');

await build({entryPoints:['server/worker.js'],outfile:'dist/server/index.js',bundle:true,format:'esm',platform:'browser',target:'es2022',
  define:{REGIONS:JSON.stringify(regions),DEPLOYMENT:JSON.stringify(deployment),SHELLS:JSON.stringify(shells),BUILD_ID:JSON.stringify(buildId)},sourcemap:false});
await mkdir('dist/.openai',{recursive:true});await cp('.openai/hosting.json','dist/.openai/hosting.json');
await cp('drizzle','dist/.openai/drizzle',{recursive:true});
console.log(`Built shared regional Worker and public assets (build ${buildId}).`);
