// Typed request errors, mapped to responses once in server/app.ts:
// ClientError (and auth.ts AuthError) -> 400 with its fixed, safe message;
// RateLimited -> 429; anything else is a dependency failure -> generic 503.
export class ClientError extends Error {}
export class RateLimited extends Error {}
