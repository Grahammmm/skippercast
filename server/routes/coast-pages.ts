import {Hono} from 'hono';
import {regions,deployment} from '../config.ts';
import {serveCoastPage,type CoastPageRegion} from '../coast-pages.ts';
import {shellResponse} from './assets.ts';
import {rateLimit} from '../middleware/rate-limit.ts';
import type {AppEnv} from '../env.ts';

// Parent registers before assets. Existing privacy/account/private routes are
// preserved; this router has only these four exact public page paths.
export const coastPages=new Hono<AppEnv>();
for(const path of ['/report','/feed.xml','/methodology','/about'])coastPages.all(path,rateLimit('FEED_LIMITER','coast-page'),async c=>{
 if(!['GET','HEAD'].includes(c.req.method))return new Response('Method not allowed',{status:405,headers:{Allow:'GET, HEAD'}});
 let template:string|undefined;
 if(path!=='/feed.xml'){const shell=await shellResponse(c,'/coast-readable.html');if(shell.ok)template=await shell.text();}
 return serveCoastPage(c.req.raw,{template,regions:regions as unknown as Readonly<Record<string,CoastPageRegion>>,publicOrigin:deployment.public_origin});
});
