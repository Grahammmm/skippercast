import test,{beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validJobClaims,verifyJobToken,resetJwksCacheForTests} from '../server/job-auth.ts';
const policy=JSON.parse(readFileSync(new URL('../deployments/production.json',import.meta.url)));
const now=1800590400,s=policy.scheduler;
beforeEach(()=>resetJwksCacheForTests());
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
  resetJwksCacheForTests();
  let requests=0;
  assert.equal(await verifyJobToken(body+'.'+signature,policy,async(url,options)=>{requests++;assert.equal(options.redirect,'manual');return new Response(null,{status:302,headers:{Location:'https://untrusted.example/keys'}});},now),false);
  assert.equal(requests,1,'key discovery must not follow a redirect');
  const changed=b64({alg:'RS256',typ:'JWT',kid:'test'})+'.'+b64({...claims,jti:'changed'});
  assert.equal(await verifyJobToken(changed+'.'+signature,policy,fetcher,now),false);
  assert.equal(await verifyJobToken('bad.token.signature',policy,fetcher,now),false);
});

// TA-M1: the advisor-media job's identity (audience /api/advisor/jobs, workflow advisor-media.yml).
const advisorScope={audiencePath:'/api/advisor/jobs',workflows:['advisor-media.yml']};
const media={...claims,aud:policy.public_origin+'/api/advisor/jobs',workflow_ref:s.repository+'/.github/workflows/advisor-media.yml@'+s.ref,event_name:'workflow_dispatch'};
test('deployments/production.json allows the trip check, the advisor-media job and the fleet jobs, and keeps the trip check workflow',()=>{
  assert.equal(s.workflow,'.github/workflows/live-conditions.yml');
  assert.deepEqual(s.workflows,['live-conditions.yml','advisor-media.yml','fleet-registry.yml','fleet-osint.yml','fleet-ais.yml','fleet-health.yml']);
});
test('an advisor scope accepts the advisor-media job for its own audience only',()=>{
  assert.equal(validJobClaims(media,policy,now,advisorScope),true);
  assert.equal(validJobClaims({...media,workflow_ref:claims.workflow_ref},policy,now,advisorScope),false,'the trip workflow is not an advisor job');
  assert.equal(validJobClaims({...media,aud:claims.aud},policy,now,advisorScope),false,'a trip-check audience is not accepted');
  for(const [key,value] of [['aud','https://attacker.test/api/advisor/jobs'],['repository_id','1'],['ref','refs/heads/other'],['event_name','pull_request'],['exp',now-1],['sub','repo:attacker/repo:ref:refs/heads/main']])assert.equal(validJobClaims({...media,[key]:value},policy,now,advisorScope),false,key);
});
test('the old call is unchanged: no scope means the trip check, which never accepts the advisor job',()=>{
  assert.equal(validJobClaims(claims,policy,now),true);
  assert.equal(validJobClaims(media,policy,now),false,'advisor-media.yml cannot call /api/jobs/check');
  assert.equal(validJobClaims({...media,aud:claims.aud},policy,now),false,'not even with the trip audience');
});
test('a scope cannot widen the deployment: a workflow missing from scheduler.workflows is refused',()=>{
  const other={...media,workflow_ref:s.repository+'/.github/workflows/deploy-cloudflare.yml@'+s.ref};
  assert.equal(validJobClaims(other,policy,now,{audiencePath:'/api/advisor/jobs',workflows:['deploy-cloudflare.yml']}),false);
  const narrow={...policy,scheduler:{...s,workflows:undefined}};
  assert.equal(validJobClaims(media,narrow,now,advisorScope),false,'without scheduler.workflows only scheduler.workflow is allowed');
  assert.equal(validJobClaims(claims,narrow,now),true);
});
test('verifyJobToken takes a scope before the fetcher; the signature check is the same',async()=>{
  const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
  const jwk={...await crypto.subtle.exportKey('jwk',pair.publicKey),kid:'test',alg:'RS256',use:'sig'};
  const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
  const sign=async c=>{const body=b64({alg:'RS256',typ:'JWT',kid:'test'})+'.'+b64(c);return body+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(body))).toString('base64url');};
  const fetcher=async()=>Response.json({keys:[jwk]});
  const advisorToken=await sign(media),tripToken=await sign(claims);
  assert.equal((await verifyJobToken(advisorToken,policy,advisorScope,fetcher,now)).jti,'unique-test-run');
  assert.equal(await verifyJobToken(advisorToken,policy,fetcher,now),false,'the old call refuses the advisor job');
  assert.ok(await verifyJobToken(tripToken,policy,fetcher,now),'the old call still accepts the trip check');
  assert.equal(await verifyJobToken(tripToken,policy,advisorScope,fetcher,now),false,'the advisor scope refuses the trip check');
  const tampered=advisorToken.split('.');tampered[1]=b64({...media,jti:'changed'});
  assert.equal(await verifyJobToken(tampered.join('.'),policy,advisorScope,fetcher,now),false);
});

// CF-01: the charter fleet jobs (audience /api/fleet/jobs, the four fleet workflows).
const fleetScope={audiencePath:'/api/fleet/jobs',workflows:['fleet-registry.yml','fleet-osint.yml','fleet-ais.yml','fleet-health.yml']};
const fleet=w=>({...claims,aud:policy.public_origin+'/api/fleet/jobs',workflow_ref:s.repository+'/.github/workflows/'+w+'@'+s.ref});
test('a fleet scope accepts the fleet workflows for the fleet audience only, and no other scope accepts them',()=>{
  for(const w of fleetScope.workflows)assert.equal(validJobClaims(fleet(w),policy,now,fleetScope),true,w);
  assert.equal(validJobClaims({...media,aud:policy.public_origin+'/api/fleet/jobs'},policy,now,fleetScope),false,'advisor-media.yml is not a fleet job');
  assert.equal(validJobClaims({...claims,aud:policy.public_origin+'/api/fleet/jobs'},policy,now,fleetScope),false,'the trip workflow is not a fleet job');
  assert.equal(validJobClaims({...fleet('fleet-ais.yml'),aud:policy.public_origin+'/api/advisor/jobs'},policy,now,fleetScope),false,'an advisor audience is refused');
  assert.equal(validJobClaims({...fleet('fleet-ais.yml'),aud:policy.public_origin+'/api/advisor/jobs'},policy,now,advisorScope),false,'a fleet job is no advisor job');
  assert.equal(validJobClaims({...fleet('fleet-ais.yml'),aud:claims.aud},policy,now),false,'nor a trip check');
  for(const [key,value] of [['repository_id','1'],['ref','refs/heads/other'],['event_name','pull_request'],['exp',now-1]])assert.equal(validJobClaims({...fleet('fleet-ais.yml'),[key]:value},policy,now,fleetScope),false,key);
});

// JWKS cache: one fetch per hour, forced refetch on an unknown kid at most once a minute, failures never cached.
test('the GitHub key set is cached, expires, handles rotation and never caches failures',async()=>{
  const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
  const gen=async kid=>{const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
    const jwk={...await crypto.subtle.exportKey('jwk',pair.publicKey),kid,alg:'RS256',use:'sig'};
    const sign=async c=>{const body=b64({alg:'RS256',typ:'JWT',kid})+'.'+b64(c);return body+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(body))).toString('base64url');};
    return {jwk,sign};};
  const a=await gen('a'),b=await gen('b'),unknown=await gen('unknown');
  const counting=(...keys)=>{const f=async()=>{f.calls++;return f.respond();};f.calls=0;f.respond=()=>Response.json({keys});return f;};
  const tok=(k,dt=0)=>k.sign({...claims,iat:now+dt,nbf:now+dt,exp:now+dt+300});
  try{
    resetJwksCacheForTests();
    let f=counting(a.jwk);
    assert.ok(await verifyJobToken(await tok(a),policy,f,now));assert.ok(await verifyJobToken(await tok(a,3599),policy,f,now+3599));
    assert.equal(f.calls,1,'two verifications inside the TTL fetch once');
    assert.ok(await verifyJobToken(await tok(a,3600),policy,f,now+3600));
    assert.equal(f.calls,2,'after the TTL the keys are fetched again');

    resetJwksCacheForTests();
    f=counting(a.jwk);f.respond=()=>new Response(null,{status:500});
    assert.equal(await verifyJobToken(await tok(a),policy,f,now),false);assert.equal(await verifyJobToken(await tok(a,1),policy,f,now+1),false);
    assert.equal(f.calls,2,'a failed fetch is not cached');
    f.respond=()=>Response.json({keys:[a.jwk]});
    assert.ok(await verifyJobToken(await tok(a,2),policy,f,now+2));assert.equal(f.calls,3);

    resetJwksCacheForTests();
    f=counting(a.jwk);
    assert.ok(await verifyJobToken(await tok(a),policy,f,now));assert.equal(f.calls,1);
    assert.equal(await verifyJobToken(await tok(b,10),policy,f,now+10),false,'b is not published yet: one refetch, still unknown');
    assert.equal(f.calls,2);
    f.respond=()=>Response.json({keys:[a.jwk,b.jwk]});
    assert.equal(await verifyJobToken(await tok(unknown,20),policy,f,now+20),false,'a second unknown kid inside the cooldown');
    assert.equal(f.calls,2,'the forced refetch is rate limited');
    assert.ok(await verifyJobToken(await tok(b,70),policy,f,now+70),'after the cooldown the rotated key is fetched and verifies');
    assert.equal(f.calls,3);

    resetJwksCacheForTests();
    f=counting(a.jwk);
    assert.equal(await verifyJobToken(await a.sign({...claims,aud:'https://attacker.test'}),policy,f,now),false);
    assert.equal(f.calls,0,'an identity policy mismatch never fetches');
  }finally{resetJwksCacheForTests();}
});
