// The SkipperCast Worker as a Hono app. Order matters: middleware runs in the
// order registered, and the first route that answers ends the request.
//
//   metrics -> request-id -> security headers (+ renewed session cookie) -> context
//   -> www redirect -> /feeds/ -> public /api/ (+ /api/telemetry) -> advisor (gated) -> fleet (gated) -> /api/auth/ -> /api/session
//   -> private gate (signed in, Origin, budget) -> private /api/ -> admin (role-gated) -> /api/ 404
//   -> static assets and page shells
//
// Errors thrown under /api/ are mapped once (middleware/error.ts).
import {Hono} from 'hono';
import {metrics} from './analytics.ts';
import {requestId} from './middleware/request-id.ts';
import {securityHeaders} from './middleware/security-headers.ts';
import {context} from './middleware/context.ts';
import {canonical} from './middleware/canonical.ts';
import {requireUser} from './middleware/auth.ts';
import {onError} from './middleware/error.ts';
import {feeds} from './routes/feeds.ts';
import {om} from './routes/om.ts';
import {publicApi} from './routes/public.ts';
import {coastData} from './routes/coast.ts';
import {coastPages} from './routes/coast-pages.ts';
import {telemetry} from './routes/telemetry.ts';
import {jobs} from './routes/jobs.ts';
import {advisorPublic} from './routes/advisor.ts';
import {fleetRouter} from './routes/fleet.ts';
import {auth} from './routes/auth.ts';
import {session, privacy} from './routes/account.ts';
import {boat} from './routes/boat.ts';
import {trips} from './routes/trips.ts';
import {subscriptions} from './routes/subscriptions.ts';
import {feedback} from './routes/feedback.ts';
// TA-W2: the Text Advisor admin (requireUser, then requireAdmin inside).
import {admin} from './routes/admin.ts';
import {assets, serveAsset} from './routes/assets.ts';
import {json} from './http.ts';
import type {AppEnv} from './env.ts';

// Routing uses the raw (percent-encoded) path, exactly as URL.pathname gives it,
// so a route sees the same path the feed-key and origin checks see.
export const app = new Hono<AppEnv>({getPath: request => new URL(request.url).pathname});

app.use('*', metrics, requestId, securityHeaders, context, canonical);
// '/feeds' and '/api' without a trailing slash are ordinary site paths.
app.all('/feeds', serveAsset);
app.all('/api', serveAsset);
app.route('/', feeds);
app.route('/', om);
app.route('/', publicApi);
app.route('/', coastData);
app.route('/', coastPages);
app.route('/', telemetry);
app.route('/', jobs);
// Text Advisor: webhooks, pages, media; 404 per request unless TEXT_ADVISOR_ENABLED=true (server/advisor/gate.ts).
app.route('/', advisorPublic);
// Charter fleet: job routes now, admin and map later; 404 per request unless FLEET_ENABLED=true (routes/fleet.ts).
app.route('/', fleetRouter);
app.route('/', auth);
app.route('/', session);
// Everything below needs a signed-in user.
app.use('/api/*', requireUser);
app.route('/', boat);
app.route('/', trips);
app.route('/', subscriptions);
app.route('/', feedback);
app.route('/', privacy);
// TA-W2: /admin, /admin.html and /api/admin/*: admins only, 404 for everyone else (routes/admin.ts).
app.route('/', admin);
app.all('/api/*', () => json({error: 'Not found'}, 404));
app.route('/', assets);
app.onError(onError);
