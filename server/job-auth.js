// Short-lived GitHub Actions identity. No scheduler password in a browser or repository.
const issuer='https://token.actions.githubusercontent.com';
const bytes=s=>{if(!/^[A-Za-z0-9_-]+$/.test(s))throw Error('Invalid token encoding');return Uint8Array.from(atob(s.replaceAll('-','+').replaceAll('_','/')+'='.repeat((4-s.length%4)%4)),c=>c.charCodeAt(0));};
const decode=s=>JSON.parse(new TextDecoder().decode(bytes(s)));
export function validJobClaims(c,policy,now=Date.now()/1000){
  const s=policy.scheduler;
  const subject=`repo:${s.repository}:ref:${s.ref}`;
  const [owner,repo]=s.repository.split('/');
  const immutable=`repo:${owner}@${s.owner_id}/${repo}@${s.repository_id}:ref:${s.ref}`;
  return c.iss===issuer&&c.aud===policy.public_origin+'/api/jobs/check'&&[subject,immutable].includes(c.sub)&&
    c.repository===s.repository&&c.repository_id===s.repository_id&&c.repository_owner_id===s.owner_id&&c.ref===s.ref&&
    c.workflow_ref===s.repository+'/'+s.workflow+'@'+s.ref&&['schedule','workflow_dispatch','push'].includes(c.event_name)&&
    [c.exp,c.nbf,c.iat].every(Number.isFinite)&&c.exp>now&&c.nbf<=now+30&&c.iat<=now+30&&c.exp-c.iat<=600&&
    typeof c.jti==='string'&&c.jti.length>0&&c.jti.length<200;
}
export async function verifyJobToken(token,policy,fetcher=fetch,now=Date.now()/1000){
  if(typeof token!=='string'||token.length>10000)return false;
  try{
    const parts=token.split('.');if(parts.length!==3)return false;
    const header=decode(parts[0]),claims=decode(parts[1]);
    if(header.alg!=='RS256'||header.typ!=='JWT'||typeof header.kid!=='string'||header.kid.length>200||!validJobClaims(claims,policy,now))return false;
    // Fixed GitHub endpoint: no jku, x5u, issuer or key URL supplied by the token is fetched.
    const response=await fetcher(issuer+'/.well-known/jwks',{signal:AbortSignal.timeout(10000),redirect:'error'});
    if(!response.ok)return false;const text=await response.text();if(text.length>50000)return false;
    const jwk=JSON.parse(text).keys.find(k=>k.kid===header.kid&&k.kty==='RSA'&&k.use==='sig'&&k.alg==='RS256');if(!jwk)return false;
    const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
    return await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,bytes(parts[2]),new TextEncoder().encode(parts[0]+'.'+parts[1]))?claims:false;
  }catch{return false;}
}
