import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validJobClaims,verifyJobToken} from '../server/job-auth.js';
const policy=JSON.parse(readFileSync(new URL('../deployments/production.json',import.meta.url)));
const now=1800590400,s=policy.scheduler;
const claims={iss:'https://token.actions.githubusercontent.com',aud:policy.public_origin+'/api/jobs/check',sub:`repo:${s.repository}:ref:${s.ref}`,repository:s.repository,repository_id:s.repository_id,repository_owner_id:s.owner_id,ref:s.ref,workflow_ref:s.repository+'/'+s.workflow+'@'+s.ref,event_name:'schedule',iat:now,nbf:now,exp:now+300,jti:'unique-test-run'};
test('scheduler policy binds identity to immutable repository IDs, branch, workflow, audience and time',()=>{
  assert.equal(validJobClaims(claims,policy,now),true);
  for(const [key,value] of [['aud','https://attacker.test'],['repository_id','1'],['repository_owner_id','2'],['ref','refs/heads/other'],['workflow_ref','other-workflow'],['event_name','pull_request'],['exp',now-1],['iat',now+3600],['sub','repo:attacker/repo:ref:refs/heads/main']])assert.equal(validJobClaims({...claims,[key]:value},policy,now),false,key);
});
test('job token requires a valid RS256 signature from the fixed GitHub JWKS endpoint',async()=>{
  const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
  const jwk={...await crypto.subtle.exportKey('jwk',pair.publicKey),kid:'test',alg:'RS256',use:'sig'};
  const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
  const body=b64({alg:'RS256',typ:'JWT',kid:'test'})+'.'+b64(claims);
  const signature=Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(body))).toString('base64url');
  const fetcher=async (url,options)=>{assert.equal(url,'https://token.actions.githubusercontent.com/.well-known/jwks');assert.equal(options.redirect,'manual');return Response.json({keys:[jwk]});};
  assert.ok(await verifyJobToken(body+'.'+signature,policy,fetcher,now));
  let requests=0;
  assert.equal(await verifyJobToken(body+'.'+signature,policy,async(url,options)=>{requests++;assert.equal(options.redirect,'manual');return new Response(null,{status:302,headers:{Location:'https://untrusted.example/keys'}});},now),false);
  assert.equal(requests,1,'key discovery must not follow a redirect');
  const changed=b64({alg:'RS256',typ:'JWT',kid:'test'})+'.'+b64({...claims,jti:'changed'});
  assert.equal(await verifyJobToken(changed+'.'+signature,policy,fetcher,now),false);
  assert.equal(await verifyJobToken('bad.token.signature',policy,fetcher,now),false);
});
