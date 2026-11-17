import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validJobClaims,verifyJobToken,resetJwksCacheForTests} from '../server/job-auth.ts';
// Synthetic, offline: claim-lifetime ordering of the scheduler identity policy.
const policy=JSON.parse(readFileSync(new URL('../deployments/production.json',import.meta.url)));
const now=1800590400,s=policy.scheduler;
const claims={iss:'https://token.actions.githubusercontent.com',aud:policy.public_origin+'/api/jobs/check',sub:`repo:${s.repository}:ref:${s.ref}`,repository:s.repository,repository_id:s.repository_id,repository_owner_id:s.owner_id,ref:s.ref,workflow_ref:s.repository+'/'+s.workflow+'@'+s.ref,event_name:'schedule',iat:now,nbf:now,exp:now+300,jti:'lifetime-test-run'};
const ok=(over)=>validJobClaims({...claims,...over},policy,now);

test('job_lifetime_rejects_reversed_times',()=>{
  assert.equal(ok({iat:now+20,exp:now+10}),false);
});
test('job_lifetime_rejects_zero_duration',()=>{
  assert.equal(ok({iat:now+10,exp:now+10}),false);
});
test('job_lifetime_preserves_ceiling_and_skew',()=>{
  assert.equal(ok({iat:now,exp:now+600}),true);
  assert.equal(ok({iat:now,exp:now+601}),false);
  assert.equal(ok({iat:now+30,exp:now+300}),true);
  assert.equal(ok({iat:now+31,exp:now+300}),false);
});
test('job_lifetime_healthy_control',()=>{
  assert.equal(ok({}),true);
  assert.equal(ok({exp:now}),false);
  for(const bad of [NaN,Infinity,String(now+300)])assert.equal(ok({exp:bad}),false,String(bad));
});
test('job_lifetime_verifier_stops_before_discovery',async()=>{
  const realFetch=globalThis.fetch;
  globalThis.fetch=()=>{throw Error('unexpected network call');};
  try{
    resetJwksCacheForTests();
    const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
    const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
    const sign=async c=>{const body=b64({alg:'RS256',typ:'JWT',kid:'test'})+'.'+b64(c);return body+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(body))).toString('base64url');};
    const jwk={...await crypto.subtle.exportKey('jwk',pair.publicKey),kid:'test',alg:'RS256',use:'sig'};
    let calls=0;
    const fetcher=async()=>{calls++;return Response.json({keys:[jwk]});};
    assert.equal(await verifyJobToken(await sign({...claims,iat:now+20,exp:now+10}),policy,fetcher,now),false);
    assert.equal(calls,0,'reversed lifetime must be refused before key discovery');
    assert.ok(await verifyJobToken(await sign(claims),policy,fetcher,now),'control token verifies');
    assert.equal(calls,1);
  }finally{globalThis.fetch=realFetch;resetJwksCacheForTests();}
});
