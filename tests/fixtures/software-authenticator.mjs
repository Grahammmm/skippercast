// A software passkey authenticator for tests. It builds real WebAuthn
// responses ("none" attestation and ES256 assertions) with
// WebCrypto, following the WebAuthn Level 3 byte layouts, so tests exercise
// the real verifier instead of a mock.
import {createHash, webcrypto} from 'node:crypto';

const subtle = webcrypto.subtle;
export const b64url = bytes => Buffer.from(bytes).toString('base64url');
const sha256 = bytes => new Uint8Array(createHash('sha256').update(bytes).digest());
const concat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
const u32 = n => new Uint8Array([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]);

// Minimal CBOR encoder: unsigned/negative ints, byte strings, text, maps.
function head(major, n) {
  if (n < 24) return new Uint8Array([(major << 5) | n]);
  if (n < 256) return new Uint8Array([(major << 5) | 24, n]);
  if (n < 65536) return new Uint8Array([(major << 5) | 25, n >> 8, n & 255]);
  return concat(new Uint8Array([(major << 5) | 26]), u32(n));
}
export function cbor(value) {
  if (typeof value === 'number') return value >= 0 ? head(0, value) : head(1, -1 - value);
  if (value instanceof Uint8Array) return concat(head(2, value.length), value);
  if (typeof value === 'string') { const b = new TextEncoder().encode(value); return concat(head(3, b.length), b); }
  if (value instanceof Map) return concat(head(5, value.size), ...[...value].flatMap(([k, v]) => [cbor(k), cbor(v)]));
  throw Error('unsupported CBOR value');
}

// WebCrypto ECDSA signatures are raw r||s; WebAuthn wants ASN.1 DER.
function der(raw) {
  const int = b => { let i = 0; while (i < b.length - 1 && b[i] === 0) i++; b = b.slice(i); return b[0] & 0x80 ? concat(new Uint8Array([0]), b) : b; };
  const r = int(raw.slice(0, 32)), s = int(raw.slice(32));
  const body = concat(new Uint8Array([2, r.length]), r, new Uint8Array([2, s.length]), s);
  return concat(new Uint8Array([0x30, body.length]), body);
}

const FLAGS = {UP: 0x01, UV: 0x04, AT: 0x40};

export class SoftwareAuthenticator {
  constructor({userVerified = true} = {}) { this.credentials = new Map(); this.userVerified = userVerified; }

  /** navigator.credentials.create() for the options JSON the server sent. */
  async create(options, origin, {rpId = options.rp.id, challenge = options.challenge, type = 'webauthn.create'} = {}) {
    const pair = await subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
    const jwk = await subtle.exportKey('jwk', pair.publicKey);
    const id = webcrypto.getRandomValues(new Uint8Array(16));
    const cose = cbor(new Map([[1, 2], [3, -7], [-1, 1], [-2, new Uint8Array(Buffer.from(jwk.x, 'base64url'))], [-3, new Uint8Array(Buffer.from(jwk.y, 'base64url'))]]));
    const flags = FLAGS.UP | FLAGS.AT | (this.userVerified ? FLAGS.UV : 0);
    const authData = concat(sha256(new TextEncoder().encode(rpId)), new Uint8Array([flags]), u32(0), new Uint8Array(16), new Uint8Array([0, id.length]), id, cose);
    const clientDataJSON = new TextEncoder().encode(JSON.stringify({type, challenge, origin, crossOrigin: false}));
    const credential = {id: b64url(id), privateKey: pair.privateKey, userHandle: options.user.id, rpId, counter: 0};
    this.credentials.set(credential.id, credential);
    return {id: credential.id, rawId: credential.id, type: 'public-key', authenticatorAttachment: 'platform', clientExtensionResults: {},
      response: {clientDataJSON: b64url(clientDataJSON), attestationObject: b64url(cbor(new Map([['fmt', 'none'], ['attStmt', new Map()], ['authData', authData]]))), transports: ['internal', 'hybrid']}};
  }

  /** navigator.credentials.get() with a discoverable credential. */
  async get(options, origin, {credentialId = [...this.credentials.keys()][0], rpId = options.rpId, challenge = options.challenge, counter} = {}) {
    const credential = this.credentials.get(credentialId);
    credential.counter = counter ?? credential.counter + 1;
    const authData = concat(sha256(new TextEncoder().encode(rpId)), new Uint8Array([FLAGS.UP | (this.userVerified ? FLAGS.UV : 0)]), u32(credential.counter));
    const clientDataJSON = new TextEncoder().encode(JSON.stringify({type: 'webauthn.get', challenge, origin, crossOrigin: false}));
    const signed = concat(authData, sha256(clientDataJSON));
    const signature = der(new Uint8Array(await subtle.sign({name: 'ECDSA', hash: 'SHA-256'}, credential.privateKey, signed)));
    return {id: credential.id, rawId: credential.id, type: 'public-key', authenticatorAttachment: 'platform', clientExtensionResults: {},
      response: {clientDataJSON: b64url(clientDataJSON), authenticatorData: b64url(authData), signature: b64url(signature), userHandle: credential.userHandle}};
  }
}
