// Short-lived GitHub Actions identity. No scheduler password in a browser or repository.
import type {Deployment, ExternalJSON} from './types.ts';

/** Verified OIDC claims; `jti` keys the per-job request budget. */
export type JobClaims = ExternalJSON & {jti: string};
const issuer='https://token.actions.githubusercontent.com';
const bytes=(s:string):Uint8Array<ArrayBuffer>=>{if(!/^[A-Za-z0-9_-]+$/.test(s))throw Error('Invalid token encoding');return Uint8Array.from(atob(s.replaceAll('-','+').replaceAll('_','/')+'='.repeat((4-s.length%4)%4)),c=>c.charCodeAt(0));};
const decode=(s:string):ExternalJSON=>JSON.parse(new TextDecoder().decode(bytes(s)));
type JobPolicy = Pick<Deployment,'scheduler'|'public_origin'>;
type Fetcher = (url:string,init:RequestInit)=>Promise<Response>;
/**
 * Which job a token may act as (TA-M1): the audience path its token was
 * requested for and the workflow files allowed to hold it. A workflow must also
 * be listed in the deployment's scheduler.workflow or scheduler.workflows, so a
 * route can narrow the policy but never widen it.
 */
export interface JobScope {audiencePath:string;workflows:readonly string[]}
const WORKFLOW_DIR='.github/workflows/';
const workflowPath=(name:string):string=>name.startsWith(WORKFLOW_DIR)?name:WORKFLOW_DIR+name;
/** The trip check's scope, the default: /api/jobs/check and scheduler.workflow (live-conditions.yml). */
export const tripCheckScope=(policy:JobPolicy):JobScope=>({audiencePath:'/api/jobs/check',workflows:[policy.scheduler.workflow]});
export function validJobClaims(c:ExternalJSON,policy:JobPolicy,now=Date.now()/1000,scope:JobScope=tripCheckScope(policy)):boolean{
  const s=policy.scheduler;
  const subject=`repo:${s.repository}:ref:${s.ref}`;
  const [owner,repo]=s.repository.split('/') as [string,string];
  const immutable=`repo:${owner}@${s.owner_id}/${repo}@${s.repository_id}:ref:${s.ref}`;
  const allowed=new Set([s.workflow,...(s.workflows??[])].map(workflowPath));
  const refs=scope.workflows.map(workflowPath).filter(w=>allowed.has(w)).map(w=>s.repository+'/'+w+'@'+s.ref);
  return c.iss===issuer&&c.aud===policy.public_origin+scope.audiencePath&&[subject,immutable].includes(c.sub)&&
    c.repository===s.repository&&c.repository_id===s.repository_id&&c.repository_owner_id===s.owner_id&&c.ref===s.ref&&
    refs.includes(c.workflow_ref)&&['schedule','workflow_dispatch','push'].includes(c.event_name)&&
    [c.exp,c.nbf,c.iat].every(Number.isFinite)&&c.exp>now&&c.nbf<=now+30&&c.iat<=now+30&&c.exp-c.iat<=600&&
    typeof c.jti==='string'&&c.jti.length>0&&c.jti.length<200;
}
/**
 * The verified claims of a GitHub Actions OIDC token, or false. Without a
 * scope it is the trip check's (tripCheckScope); TA-M1's advisor jobs pass
 * {audiencePath: '/api/advisor/jobs', workflows: ['advisor-media.yml']}.
 */
export function verifyJobToken(token:unknown,policy:JobPolicy,fetcher?:Fetcher,now?:number):Promise<JobClaims|false>;
export function verifyJobToken(token:unknown,policy:JobPolicy,scope:JobScope,fetcher?:Fetcher,now?:number):Promise<JobClaims|false>;
export async function verifyJobToken(token:unknown,policy:JobPolicy,...rest:[Fetcher?,number?]|[JobScope,Fetcher?,number?]):Promise<JobClaims|false>{
  const scope=typeof rest[0]==='object'&&rest[0]!==null?rest[0] as JobScope:tripCheckScope(policy);
  const [fetcher=fetch,now=Date.now()/1000]=(typeof rest[0]==='object'&&rest[0]!==null?rest.slice(1):rest) as [Fetcher?,number?];
  if(typeof token!=='string'||token.length>10000)return false;
  let stage='decode';
  try{
    const parts=token.split('.') as [string,string,string];if(parts.length!==3)return false;
    const header=decode(parts[0]),claims=decode(parts[1]);
    if(header.alg!=='RS256'||header.typ!=='JWT'||typeof header.kid!=='string'||header.kid.length>200)return false;
    if(!validJobClaims(claims,policy,now,scope)){console.warn('Scheduler identity policy mismatch');return false;}
    // Fixed GitHub endpoint: no jku, x5u, issuer or key URL supplied by the token is fetched.
    stage='jwks-fetch';const response=await fetcher(issuer+'/.well-known/jwks',{signal:AbortSignal.timeout(10000),redirect:'manual'});
    if(!response.ok){console.warn('Scheduler key discovery failed',{status:response.status});return false;}const text=await response.text();if(text.length>50000)return false;
    stage='jwks-key';const jwk=JSON.parse(text).keys.find((k:ExternalJSON)=>k.kid===header.kid&&k.kty==='RSA'&&k.use==='sig'&&k.alg==='RS256');if(!jwk){console.warn('Scheduler signing key unavailable');return false;}
    stage='signature';
    const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
    return await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,bytes(parts[2]),new TextEncoder().encode(parts[0]+'.'+parts[1]))?claims:false;
  }catch(error){if(stage!=='decode')console.error('Scheduler identity verification unavailable',{stage,reason:String((error as Error).message).slice(0,200)});return false;}
}
