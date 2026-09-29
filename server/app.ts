// The SkipperCast Worker as a Hono app. Order matters: middleware runs in the
// order registered, and the first route that answers ends the request.
//
//   request-id -> security headers (+ renewed session cookie) -> context
//   -> www redirect -> /feeds/ -> public /api/ -> /api/auth/ -> /api/session
//   -> private gate (signed in, Origin, budget) -> private /api/ -> /api/ 404
//   -> static assets and page shells
//
// Errors thrown under /api/ are mapped once (middleware/error.ts).
import {Hono} from 'hono';
import {requestId} from './middleware/request-id.ts';
import {securityHeaders} from './middleware/security-headers.ts';
import {context} from './middleware/context.ts';
import {canonical} from './middleware/canonical.ts';
import {requireUser} from './middleware/auth.ts';
import {onError} from './middleware/error.ts';
import {feeds} from './routes/feeds.ts';
import {om} from './routes/om.ts';
import {publicApi} from './routes/public.ts';
import {jobs} from './routes/jobs.ts';
import {auth} from './routes/auth.ts';
import {session, privacy} from './routes/account.ts';
import {boat} from './routes/boat.ts';
import {trips} from './routes/trips.ts';
import {subscriptions} from './routes/subscriptions.ts';
import {feedback} from './routes/feedback.ts';
import {assets, serveAsset} from './routes/assets.ts';
import {json} from './http.ts';
import type {AppEnv} from './env.ts';

// Routing uses the raw (percent-encoded) path, exactly as URL.pathname gives it,
// so a route sees the same path the feed-key and origin checks see.
export const app = new Hono<AppEnv>({getPath: request => new URL(request.url).pathname});

app.use('*', requestId, securityHeaders, context, canonical);
// '/feeds' and '/api' without a trailing slash are ordinary site paths.
app.all('/feeds', serveAsset);
app.all('/api', serveAsset);
app.route('/', feeds);
app.route('/', om);
app.route('/', publicApi);
app.route('/', jobs);
app.route('/', auth);
app.route('/', session);
// Everything below needs a signed-in user.
app.use('/api/*', requireUser);
app.route('/', boat);
app.route('/', trips);
app.route('/', subscriptions);
app.route('/', feedback);
app.route('/', privacy);
app.all('/api/*', () => json({error: 'Not found'}, 404));
app.route('/', assets);
app.onError(onError);
