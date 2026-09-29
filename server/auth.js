// SkipperCast accounts: passkeys (WebAuthn) and a first-party session cookie.
// No passwords, email or third-party sign-in. The server stores each passkey's
// public key and signature counter, sha256 of each session token (never the
// token), and single-use challenges that expire after five minutes.
import {generateRegistrationOptions,verifyRegistrationResponse,generateAuthenticationOptions,verifyAuthenticationResponse} from '@simplewebauthn/server';

export const COOKIE='__Host-sc_session';
export const SESSION_SECONDS=30*86400;      // 30-day sliding session
export const RENEW_BELOW_SECONDS=15*86400;  // renewed once less than 15 days remain
export const CHALLENGE_SECONDS=300;         // challenges are single-use and live 5 minutes
export const MAX_PASSKEYS=10;
export const SIGN_IN_PATH='/#account';
const RP_NAME='SkipperCast';

export class AuthError extends Error {}     // answered 400 with its fixed message

const now=()=>Math.floor(Date.now()/1000);
const iso=()=>new Date().toISOString();
const b64url=bytes=>{let s='';for(const b of bytes)s+=String.fromCharCode(b);return btoa(s).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');};
const fromB64url=text=>Uint8Array.from(atob(text.replaceAll('-','+').replaceAll('_','/')+'='.repeat((4-text.length%4)%4)),c=>c.charCodeAt(0));
const sha256=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join('');
const TRANSPORTS=new Set(['ble','cable','hybrid','internal','nfc','smart-card','usb']);
const cleanTransports=list=>Array.isArray(list)?list.filter(t=>TRANSPORTS.has(t)):[];

/** A display name the person chose, or null. Plain text, 1-60 characters. */
export function displayName(value){
  if(value==null||value==='')return null;
  if(typeof value!=='string')throw new AuthError('invalid name');
  const name=value.replace(/[\u0000-\u001f\u007f]/g,'').trim().slice(0,60);
  return name||null;
}

/** The RP ID is the request's own host; the origin must be one this deployment allows. */
export function relyingParty(url,allowed){
  if(!allowed.has(url.origin))throw new AuthError('this address cannot use accounts');
  return {rpID:url.hostname,origin:url.origin};
}

function cookieValue(request){
  for(const part of (request.headers.get('Cookie')||'').split(';')){
    const i=part.indexOf('=');if(i<0)continue;
    if(part.slice(0,i).trim()===COOKIE){const v=part.slice(i+1).trim();return /^[\w-]{43}$/.test(v)?v:null;}
  }
  return null;
}
export function sessionCookie(token,maxAge=SESSION_SECONDS){
  return `${COOKIE}=${token}; Max-Age=${maxAge}; Path=/; Secure; HttpOnly; SameSite=Lax`;
}
export const clearCookie=()=>`${COOKIE}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax`;

/**
 * The signed-in user for this request, or null. Renews a session with less
 * than 15 days left: `renewed` then carries the Set-Cookie value to send.
 */
export async function sessionUser(request,database){
  const token=cookieValue(request);if(!token)return null;
  const db=typeof database==='function'?database():database;   // storage is touched only for a session cookie
  const id=await sha256(token),t=now();
  const row=await db.prepare('SELECT s.user_id,s.expires_at,u.display_name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=?').bind(id).first();
  if(!row)return null;
  if(row.expires_at<=t){await db.prepare('DELETE FROM sessions WHERE id=?').bind(id).run();return null;}
  let renewed=null;
  if(row.expires_at-t<RENEW_BELOW_SECONDS){
    await db.prepare('UPDATE sessions SET expires_at=? WHERE id=?').bind(t+SESSION_SECONDS,id).run();
    renewed=sessionCookie(token);
  }
  return {id:row.user_id,display_name:row.display_name,sessionId:id,renewed};
}

async function startSession(db,userId,request){
  const token=b64url(crypto.getRandomValues(new Uint8Array(32)));
  const ua=(request.headers.get('User-Agent')||'').replace(/[^\x20-\x7e]/g,'').slice(0,80)||null;
  await db.prepare('INSERT INTO sessions(id,user_id,created_at,expires_at,user_agent) VALUES(?,?,?,?,?)').bind(await sha256(token),userId,iso(),now()+SESSION_SECONDS,ua).run();
  return sessionCookie(token);
}

async function issueChallenge(db,kind,userId,challenge){
  await db.prepare('INSERT INTO auth_challenges(id,challenge,kind,user_id,expires_at) VALUES(?,?,?,?,?)').bind(crypto.randomUUID(),challenge,kind,userId,now()+CHALLENGE_SECONDS).run();
}
/** Delete the challenge (single use) and return its row if it was live and of this kind. */
async function consumeChallenge(db,challenge,kind){
  if(typeof challenge!=='string'||challenge.length>200)return null;
  const row=await db.prepare('DELETE FROM auth_challenges WHERE challenge=? RETURNING kind,user_id,expires_at').bind(challenge).first();
  return row&&row.kind===kind&&row.expires_at>now()?row:null;
}
function credentialJSON(input){
  const r=input?.response;
  if(!r||typeof r!=='object'||typeof r.id!=='string'||r.id.length>1400||!/^[\w-]+$/.test(r.id)||r.type!=='public-key'||typeof r.response!=='object')throw new AuthError('invalid passkey response');
  return r;
}

async function registrationOptions(db,rp,userId,{name,exclude=[]}){
  const options=await generateRegistrationOptions({rpName:RP_NAME,rpID:rp.rpID,userID:fromB64url(userId),userName:name||'SkipperCast account',userDisplayName:name||'',
    attestationType:'none',excludeCredentials:exclude.map(p=>({id:p.id,transports:JSON.parse(p.transports||'[]')})),
    authenticatorSelection:{residentKey:'required',userVerification:'required'},timeout:CHALLENGE_SECONDS*1000});
  return options;
}
async function verifyRegistration(db,rp,input,kind){
  const response=credentialJSON(input);let consumed;
  let result;
  try{
    result=await verifyRegistrationResponse({response,expectedOrigin:rp.origin,expectedRPID:rp.rpID,requireUserVerification:true,
      expectedChallenge:async c=>!!(consumed=await consumeChallenge(db,c,kind))});
  }catch(error){if(consumed===null)throw new AuthError('this sign-in request expired; try again');throw new AuthError('passkey could not be verified');}
  if(!result.verified||!consumed?.user_id)throw new AuthError('passkey could not be verified');
  const c=result.registrationInfo.credential;
  return {userId:consumed.user_id,passkey:{id:c.id,public_key:b64url(c.publicKey),counter:c.counter,transports:JSON.stringify(cleanTransports(c.transports??response.response.transports))}};
}
const insertPasskey=(db,userId,p)=>db.prepare('INSERT INTO passkeys(id,user_id,public_key,counter,transports,created_at) VALUES(?,?,?,?,?,?)').bind(p.id,userId,p.public_key,p.counter,p.transports,iso());

/**
 * Handles /api/auth/*. Returns a Response, or null for an unknown path.
 * `json(data,status)` builds responses; `current` is the session user or null.
 */
export async function authRoute(request,{path,db,rp,body,json,current}){
  const method=request.method;
  const withCookie=(response,cookie)=>{response.headers.append('Set-Cookie',cookie);return response;};
  // Signing in or creating an account ends any session this browser already had.
  const endCurrent=async()=>{if(current)await db.prepare('DELETE FROM sessions WHERE id=?').bind(current.sessionId).run();};

  if(path==='/api/auth/register/options'&&method==='POST'){
    const input=await body(request),name=displayName(input.display_name);
    const userId=b64url(crypto.getRandomValues(new Uint8Array(16)));
    const options=await registrationOptions(db,rp,userId,{name});
    await issueChallenge(db,'register',userId,options.challenge);
    return json(options);
  }
  if(path==='/api/auth/register/verify'&&method==='POST'){
    const input=await body(request),name=displayName(input.display_name);
    const {userId,passkey}=await verifyRegistration(db,rp,input,'register');
    if(await db.prepare('SELECT id FROM passkeys WHERE id=?').bind(passkey.id).first())throw new AuthError('this passkey is already registered; sign in instead');
    await db.batch([db.prepare('INSERT INTO users(id,created_at,display_name) VALUES(?,?,?)').bind(userId,iso(),name),insertPasskey(db,userId,passkey)]);
    await endCurrent();
    return withCookie(json({signedIn:true,user:{id:userId,display_name:name}},201),await startSession(db,userId,request));
  }
  if(path==='/api/auth/login/options'&&method==='POST'){
    const options=await generateAuthenticationOptions({rpID:rp.rpID,userVerification:'required',timeout:CHALLENGE_SECONDS*1000});
    await issueChallenge(db,'login',null,options.challenge);
    return json(options);
  }
  if(path==='/api/auth/login/verify'&&method==='POST'){
    const response=credentialJSON(await body(request));
    const stored=await db.prepare('SELECT p.*,u.display_name FROM passkeys p JOIN users u ON u.id=p.user_id WHERE p.id=?').bind(response.id).first();
    let consumed,result;
    try{
      if(!stored){
        // Still spend the challenge, so an unknown passkey cannot probe it twice.
        const clientData=JSON.parse(new TextDecoder().decode(fromB64url(String(response.response.clientDataJSON||''))));
        await consumeChallenge(db,clientData.challenge,'login');throw new AuthError('unknown');
      }
      result=await verifyAuthenticationResponse({response,expectedOrigin:rp.origin,expectedRPID:rp.rpID,requireUserVerification:true,
        credential:{id:stored.id,publicKey:fromB64url(stored.public_key),counter:stored.counter,transports:JSON.parse(stored.transports||'[]')},
        expectedChallenge:async c=>!!(consumed=await consumeChallenge(db,c,'login'))});
    }catch{throw new AuthError(stored&&consumed===null?'this sign-in request expired; try again':'that passkey is not recognised here');}
    if(!result.verified||!consumed)throw new AuthError('that passkey is not recognised here');
    await db.prepare('UPDATE passkeys SET counter=?,last_used_at=? WHERE id=?').bind(result.authenticationInfo.newCounter,iso(),stored.id).run();
    await endCurrent();
    return withCookie(json({signedIn:true,user:{id:stored.user_id,display_name:stored.display_name}}),await startSession(db,stored.user_id,request));
  }
  if(path==='/api/auth/logout'&&method==='POST'){
    await endCurrent();
    return withCookie(json({signedIn:false}),clearCookie());
  }

  // Managing passkeys needs a session.
  if(!path.startsWith('/api/auth/passkeys'))return null;
  if(!current)return json({error:'Sign in to manage passkeys',signIn:SIGN_IN_PATH},401);
  const mine=async()=>(await db.prepare('SELECT id,transports,created_at,last_used_at FROM passkeys WHERE user_id=? ORDER BY created_at').bind(current.id).all()).results;
  if(path==='/api/auth/passkeys'&&method==='GET')
    return json({passkeys:(await mine()).map(p=>({id:p.id,transports:JSON.parse(p.transports||'[]'),created_at:p.created_at,last_used_at:p.last_used_at}))});
  if(path==='/api/auth/passkeys/options'&&method==='POST'){
    const existing=await mine();if(existing.length>=MAX_PASSKEYS)return json({error:`Limit of ${MAX_PASSKEYS} passkeys`},409);
    const options=await registrationOptions(db,rp,current.id,{name:current.display_name,exclude:existing});
    await issueChallenge(db,'add',current.id,options.challenge);
    return json(options);
  }
  if(path==='/api/auth/passkeys'&&method==='POST'){
    const {userId,passkey}=await verifyRegistration(db,rp,await body(request),'add');
    if(userId!==current.id)throw new AuthError('passkey could not be verified');
    if(await db.prepare('SELECT id FROM passkeys WHERE id=?').bind(passkey.id).first())throw new AuthError('this passkey is already registered');
    if((await mine()).length>=MAX_PASSKEYS)return json({error:`Limit of ${MAX_PASSKEYS} passkeys`},409);
    await insertPasskey(db,current.id,passkey).run();
    return json({added:true,id:passkey.id},201);
  }
  if(path==='/api/auth/passkeys'&&method==='DELETE'){
    const {id}=await body(request);if(typeof id!=='string'||!id||id.length>1400)throw new AuthError('passkey id required');
    const existing=await mine();if(!existing.some(p=>p.id===id))return json({error:'Not found'},404);
    const onlyOne=json({error:'This is your only passkey. Add another before removing it, or delete the account.'},409);
    if(existing.length<2)return onlyOne;
    // The count is re-checked in the same statement, so two parallel removals cannot delete the last passkey.
    const removed=await db.prepare('DELETE FROM passkeys WHERE id=? AND user_id=? AND (SELECT COUNT(*) FROM passkeys WHERE user_id=?)>1').bind(id,current.id,current.id).run();
    if(!removed?.meta?.changes)return onlyOne;
    return json({removed:true});
  }
  return null;
}

/** Everything an account owns outside the trip tables, for export and deletion. */
export async function exportAccount(db,userId){
  return {user:await db.prepare('SELECT id,created_at,display_name FROM users WHERE id=?').bind(userId).first(),
    passkeys:(await db.prepare('SELECT id,transports,created_at,last_used_at FROM passkeys WHERE user_id=?').bind(userId).all()).results,
    sessions:(await db.prepare('SELECT created_at,expires_at,user_agent FROM sessions WHERE user_id=?').bind(userId).all()).results};
}
export const deleteAccountStatements=(db,userId)=>['passkeys','sessions','auth_challenges'].map(t=>db.prepare(`DELETE FROM ${t} WHERE user_id=?`).bind(userId)).concat(db.prepare('DELETE FROM users WHERE id=?').bind(userId));
