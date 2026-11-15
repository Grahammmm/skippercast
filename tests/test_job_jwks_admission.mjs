import test,{beforeEach,afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {verifyJobToken,resetJwksCacheForTests} from '../server/job-auth.ts';
// Structural JWKS admission: a malformed row container must never be cached, whatever else the key set holds.
const policy=JSON.parse(readFileSync(new URL('../deployments/production.json',import.meta.url)));
const now=1800590400,s=policy.scheduler;
const claims={iss:'https://token.actions.githubusercontent.com',aud:policy.public_origin+'/api/jobs/check',sub:`repo:${s.repository}:ref:${s.ref}`,repository:s.repository,repository_id:s.repository_id,repository_owner_id:s.owner_id,ref:s.ref,workflow_ref:s.repository+'/'+s.workflow+'@'+s.ref,event_name:'schedule',iat:now,nbf:now,exp:now+300,jti:'jwks-admission'};
const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
const gen=async kid=>{
  const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
  const jwk={...await crypto.subtle.exportKey('jwk',pair.publicKey),kid,alg:'RS256',use:'sig'};
  const sign=async(c,dt=0)=>{const body=b64({alg:'RS256',typ:'JWT',kid})+'.'+b64({...c,iat:now+dt,nbf:now+dt,exp:now+dt+300});return body+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(body))).toString('base64url');};
  return {jwk,sign};
};
// Scripted discovery: each call answers the next queued body (the last one repeats).
const discovery=(...bodies)=>{const f=async()=>{const body=bodies[Math.min(f.calls,bodies.length-1)];f.calls++;return typeof body==='string'?new Response(body):Response.json(body);};f.calls=0;return f;};
const realFetch=globalThis.fetch,realWarn=console.warn,realError=console.error;
beforeEach(()=>{resetJwksCacheForTests();globalThis.fetch=()=>{throw Error('unexpected network use');};console.warn=()=>{};console.error=()=>{};});
afterEach(()=>{globalThis.fetch=realFetch;console.warn=realWarn;console.error=realError;resetJwksCacheForTests();});

test('null_discovery_is_not_cached_and_next_request_recovers',async()=>{
  const a=await gen('a'),f=discovery({keys:[null]},{keys:[a.jwk]});
  assert.equal(await verifyJobToken(await a.sign(claims),policy,f,now),false);assert.equal(f.calls,1);
  assert.equal((await verifyJobToken(await a.sign(claims,1),policy,f,now+1)).jti,'jwks-admission');assert.equal(f.calls,2,'the malformed set was not cached');
  assert.ok(await verifyJobToken(await a.sign(claims,2),policy,f,now+2));assert.equal(f.calls,2,'the healthy set is cached');
});

test('mixed_null_and_valid_key_refuses_atomically',async()=>{
  const a=await gen('a');
  for(const rows of [[null,a.jwk],[a.jwk,null]]){
    resetJwksCacheForTests();
    const f=discovery({keys:rows},{keys:[a.jwk]});
    assert.equal(await verifyJobToken(await a.sign(claims),policy,f,now),false,'a partly malformed set is refused whole');assert.equal(f.calls,1);
    assert.ok(await verifyJobToken(await a.sign(claims,1),policy,f,now+1));assert.equal(f.calls,2);
  }
});

test('primitive_and_array_rows_refuse_without_poisoning',async()=>{
  const a=await gen('a');
  for(const row of ['text',7,true,[],[{kid:'a'}]]){
    resetJwksCacheForTests();
    const f=discovery({keys:[row]},{keys:[a.jwk]});
    assert.equal(await verifyJobToken(await a.sign(claims),policy,f,now),false,JSON.stringify(row));
    assert.ok(await verifyJobToken(await a.sign(claims,1),policy,f,now+1),'recovers after '+JSON.stringify(row));assert.equal(f.calls,2);
  }
  for(const body of [{},{keys:{}},{keys:'a'},[],'not json',null]){
    resetJwksCacheForTests();
    const f=discovery(typeof body==='string'?body:JSON.stringify(body),{keys:[a.jwk]});
    assert.equal(await verifyJobToken(await a.sign(claims),policy,f,now),false,'control '+JSON.stringify(body));
    assert.ok(await verifyJobToken(await a.sign(claims,1),policy,f,now+1));assert.equal(f.calls,2);
  }
});

test('healthy_heterogeneous_set_retains_selection',async()=>{
  const a=await gen('a'),other={kty:'EC',crv:'P-256',kid:'ec',use:'sig',alg:'ES256',x:'x',y:'y',key_ops:['verify'],extra:{nested:[1]}};
  const f=discovery({keys:[other,{kty:'RSA',kid:'a',use:'enc',alg:'RSA-OAEP'},a.jwk],issuer:'ignored'});
  assert.ok(await verifyJobToken(await a.sign(claims),policy,f,now));assert.ok(await verifyJobToken(await a.sign(claims,5),policy,f,now+5));
  assert.equal(f.calls,1,'the healthy set is reused inside the TTL');
  resetJwksCacheForTests();
  const empty=discovery({keys:[]}),b=await gen('b');
  assert.equal(await verifyJobToken(await b.sign(claims),policy,empty,now),false,'an empty set has no usable key');
  assert.equal(empty.calls,1,'an empty set is cached like any other healthy set');
  assert.equal(await verifyJobToken(await b.sign(claims,1),policy,discovery({keys:[a.jwk]}),now+1),false,'an unknown kid is refused even after the forced refetch');
});

test('bad_forced_refresh_preserves_old_key_and_cooldown',async()=>{
  const a=await gen('a'),b=await gen('b'),f=discovery({keys:[a.jwk]},{keys:[null]},{keys:[a.jwk,b.jwk]});
  assert.ok(await verifyJobToken(await a.sign(claims),policy,f,now));assert.equal(f.calls,1);
  assert.equal(await verifyJobToken(await b.sign(claims,10),policy,f,now+10),false,'unknown kid forces a refresh that is malformed');assert.equal(f.calls,2);
  assert.ok(await verifyJobToken(await a.sign(claims,11),policy,f,now+11),'the old healthy set survives the bad refresh');assert.equal(f.calls,2);
  assert.equal(await verifyJobToken(await b.sign(claims,20),policy,f,now+20),false,'still inside the cooldown');assert.equal(f.calls,2,'a malformed refresh does not bypass the cooldown');
  assert.ok(await verifyJobToken(await b.sign(claims,70),policy,f,now+70),'after the cooldown the healthy set admits b');assert.equal(f.calls,3);
});

test('expired_cache_bad_discovery_retries_without_renewal',async()=>{
  const a=await gen('a'),evil=await gen('a'),f=discovery({keys:[a.jwk]},{keys:[evil.jwk,'x']},{keys:[a.jwk]});
  assert.ok(await verifyJobToken(await a.sign(claims),policy,f,now));
  assert.equal(await verifyJobToken(await a.sign(claims,3600),policy,f,now+3600),false,'expired cache plus malformed discovery fails closed');assert.equal(f.calls,2);
  assert.equal(await verifyJobToken(await evil.sign(claims,3600),policy,f,now+3600),false,'a key from a refused set is not trusted');
  assert.equal(f.calls,3,'the expired cache was not renewed, so discovery was retried');
  assert.ok(await verifyJobToken(await a.sign(claims,3601),policy,f,now+3601));assert.equal(f.calls,3,'the healthy set is cached');
});

test('claim_and_crypto_guards_unchanged',async()=>{
  const a=await gen('a'),f=discovery({keys:[a.jwk]});
  for(const [key,value] of [['aud','https://attacker.test'],['workflow_ref','other-workflow'],['iss','https://attacker.test']])
    assert.equal(await verifyJobToken(await a.sign({...claims,[key]:value}),policy,f,now),false,key);
  assert.equal(await verifyJobToken(await a.sign(claims,-3600),policy,f,now),false,'expired');
  assert.equal(f.calls,0,'a policy mismatch never fetches');
  const token=(await a.sign(claims)).split('.');token[1]=b64({...claims,jti:'changed'});
  assert.equal(await verifyJobToken(token.join('.'),policy,f,now),false,'a tampered payload fails the signature');
  assert.equal(f.calls,1);
});
