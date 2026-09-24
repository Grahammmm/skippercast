import {build} from 'esbuild';
import {readdir,readFile,mkdir,cp,rm,writeFile} from 'node:fs/promises';
const regions={};const draftRegions=[];for(const id of await readdir('regions')){const region=JSON.parse(await readFile(`regions/${id}/region.json`,'utf8'));if(region.status==='draft')draftRegions.push(region);else regions[id]=region;}
const deployment=JSON.parse(await readFile('deployments/production.json','utf8'));
await rm('dist/client',{recursive:true,force:true});await mkdir('dist/client',{recursive:true});
for(const entry of await readdir('dist'))if(!['client','server','.openai'].includes(entry))await cp(`dist/${entry}`,`dist/client/${entry}`,{recursive:true});
const publicRules=new Set(Object.values(regions).map(region=>region.assets.regulations));
for(const region of draftRegions){const asset=region.assets.regulations;if(asset&&!publicRules.has(asset))await rm(`dist/client/${asset}`,{force:true});}
await build({entryPoints:['server/worker.js'],outfile:'dist/server/index.js',bundle:true,format:'esm',platform:'browser',target:'es2022',define:{REGIONS:JSON.stringify(regions),DEPLOYMENT:JSON.stringify(deployment)},sourcemap:false});
await mkdir('dist/.openai',{recursive:true});await cp('.openai/hosting.json','dist/.openai/hosting.json');
await cp('drizzle','dist/.openai/drizzle',{recursive:true});
console.log('Built shared regional Worker and public assets.');
