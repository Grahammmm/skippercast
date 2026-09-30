import {sqliteTable, text, integer, real, index, uniqueIndex} from 'drizzle-orm/sqlite-core';

export const trips=sqliteTable('trips',{
  id:text('id').primaryKey(), owner:text('owner').notNull(), region:text('region').notNull(),
  point:text('point').notNull(), species:text('species').notNull(), date:text('date').notNull(),
  startHour:integer('start_hour').notNull(),endHour:integer('end_hour').notNull(),
  windLimit:real('wind_limit').notNull(),gustLimit:real('gust_limit').notNull(),seaLimit:real('sea_limit').notNull(),
  enabled:integer('enabled').notNull().default(1), createdAt:text('created_at').notNull(),
  lastAssessment:text('last_assessment'),finalDeliveredAt:text('final_delivered_at'),
  // Saved boat when the trip was saved (dist/boat-handling.js factors); null = reference boat.
  boatName:text('boat_name'),boatSea:real('boat_sea'),boatWind:real('boat_wind'),boatChopPeriod:real('boat_chop_period'),
},t=>[index('trip_owner').on(t.owner),index('trip_due').on(t.enabled,t.date)]);
export const subscriptions=sqliteTable('subscriptions',{
  id:text('id').primaryKey(),owner:text('owner').notNull(),endpoint:text('endpoint').notNull(),
  p256dh:text('p256dh').notNull(),auth:text('auth').notNull(),createdAt:text('created_at').notNull(),
},t=>[index('subscription_owner').on(t.owner),uniqueIndex('subscription_endpoint').on(t.endpoint)]);
export const events=sqliteTable('alert_events',{
  id:text('id').primaryKey(),tripId:text('trip_id').notNull(),owner:text('owner').notNull(),
  kind:text('kind').notNull(),message:text('message').notNull(),createdAt:text('created_at').notNull(),
  status:text('status').notNull().default('pending'),deliveredAt:text('delivered_at'),
},t=>[index('event_owner_date').on(t.owner,t.createdAt),index('event_status').on(t.status)]);
export const receipts=sqliteTable('delivery_receipts',{
  id:text('id').primaryKey(),eventId:text('event_id').notNull(),subscriptionId:text('subscription_id').notNull(),
  status:text('status').notNull(),attemptAt:text('attempt_at').notNull(),httpStatus:integer('http_status'),
},t=>[index('receipt_event').on(t.eventId)]);
export const feedback=sqliteTable('comfort_feedback',{
  id:text('id').primaryKey(),owner:text('owner').notNull(),region:text('region').notNull(),
  observedAt:text('observed_at').notNull(),rating:integer('rating').notNull(),context:text('context').notNull(),
},t=>[index('feedback_owner').on(t.owner)]);
export const limits=sqliteTable('request_limits',{
  id:text('id').primaryKey(),count:integer('count').notNull(),expiresAt:integer('expires_at').notNull(),
},t=>[index('limit_expires').on(t.expiresAt)]);

// SkipperCast accounts (passkeys only; no passwords or email). `owner` in the
// tables above holds users.id. Sessions and challenges store only what the
// server issued: sessions.id is sha256(token), never the cookie value.
export const users=sqliteTable('users',{
  id:text('id').primaryKey(),createdAt:text('created_at').notNull(),displayName:text('display_name'),
});
export const passkeys=sqliteTable('passkeys',{
  id:text('id').primaryKey(),userId:text('user_id').notNull(),publicKey:text('public_key').notNull(),
  counter:integer('counter').notNull().default(0),transports:text('transports'),
  createdAt:text('created_at').notNull(),lastUsedAt:text('last_used_at'),
},t=>[index('passkey_user').on(t.userId)]);
export const sessions=sqliteTable('sessions',{
  id:text('id').primaryKey(),userId:text('user_id').notNull(),createdAt:text('created_at').notNull(),
  expiresAt:integer('expires_at').notNull(),userAgent:text('user_agent'),
},t=>[index('session_user').on(t.userId),index('session_expires').on(t.expiresAt)]);
export const challenges=sqliteTable('auth_challenges',{
  id:text('id').primaryKey(),challenge:text('challenge').notNull(),kind:text('kind').notNull(),
  userId:text('user_id'),expiresAt:integer('expires_at').notNull(),
},t=>[uniqueIndex('challenge_value').on(t.challenge),index('challenge_expires').on(t.expiresAt)]);

// Small key/value state for the Worker's own background jobs (P3-04): e.g. the
// last live-conditions publication whose trip checks were queued. No user data.
export const jobState=sqliteTable('job_state',{
  key:text('key').primaryKey(),value:text('value').notNull(),updatedAt:text('updated_at').notNull(),
});
