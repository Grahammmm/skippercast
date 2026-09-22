import {build} from 'esbuild';
import {readdir,readFile,mkdir,cp,rm,writeFile} from 'node:fs/promises';
const regions={};for(const id of await readdir('regions')){regions[id]=JSON.parse(await readFile(`regions/${id}/region.json`,'utf8'));}
const deployment=JSON.parse(await readFile('deployments/production.json','utf8'));
await rm('dist/client',{recursive:true,force:true});await mkdir('dist/client',{recursive:true});
for(const entry of await readdir('dist'))if(!['client','server','.openai'].includes(entry))await cp(`dist/${entry}`,`dist/client/${entry}`,{recursive:true});
await build({entryPoints:['server/worker.js'],outfile:'dist/server/index.js',bundle:true,format:'esm',platform:'browser',target:'es2022',define:{REGIONS:JSON.stringify(regions),DEPLOYMENT:JSON.stringify(deployment)},sourcemap:false});
await mkdir('dist/.openai',{recursive:true});await cp('.openai/hosting.json','dist/.openai/hosting.json');
await cp('drizzle','dist/.openai/drizzle',{recursive:true});
console.log('Built shared regional Worker and public assets.');
