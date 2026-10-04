import {sqliteTable, text, integer, real, index, uniqueIndex, primaryKey} from 'drizzle-orm/sqlite-core';

export const trips=sqliteTable('trips',{
  id:text('id').primaryKey(), owner:text('owner').notNull(), region:text('region').notNull(),
  point:text('point').notNull(), species:text('species').notNull(), date:text('date').notNull(),
  startHour:integer('start_hour').notNull(),endHour:integer('end_hour').notNull(),
  windLimit:real('wind_limit').notNull(),gustLimit:real('gust_limit').notNull(),seaLimit:real('sea_limit').notNull(),
  enabled:integer('enabled').notNull().default(1), createdAt:text('created_at').notNull(),
  lastAssessment:text('last_assessment'),finalDeliveredAt:text('final_delivered_at'),
  // Saved boat when the trip was saved (dist/boat-handling.js factors); null = reference boat.
  boatName:text('boat_name'),boatSea:real('boat_sea'),boatWind:real('boat_wind'),boatChopPeriod:real('boat_chop_period'),
  // The planned trip (server/trips.ts validateTripPlan): where it launches, the
  // target species beyond the primary one, and the JSON plan of spots, legs, the
  // window and the exports taken. Null on trips saved before the planner.
  launchPoint:text('launch_point'),targets:text('targets'),plan:text('plan'),
  status:text('status').notNull().default('planned'),updatedAt:text('updated_at'),
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
  // 'admin' or null. Set only by scripts/advisor/grant-admin.mjs; /api/session never
  // exposes it beyond is_admin (docs/plans/text-advisor/02-data-model.md).
  role:text('role'),
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

// Text Advisor core (docs/plans/text-advisor/02-data-model.md, migration 0006).
// No phone number is stored in clear: phone_hash is HMAC-SHA256 under a key
// derived from ADVISOR_PHONE_KEY (lookup), phone_enc is AES-GCM (sending only);
// see server/advisor/contacts.ts. Bodies and media live here and in the private
// ADVISOR_MEDIA bucket, never in git, feeds or analytics. "Forget me" deletes a
// contact's rows from every table below (forgetContact).

// One row per person (phone number) or web visitor (web_session = sha256 of the
// sc_adv cookie). status 'stopped' (texted STOP) means no outbound of any kind.
export const advisorContacts=sqliteTable('advisor_contacts',{
  id:text('id').primaryKey(),phoneHash:text('phone_hash'),phoneEnc:text('phone_enc'),webSession:text('web_session'),
  channel:text('channel').notNull(),role:text('role').notNull().default('angler'),boatId:text('boat_id'),
  displayName:text('display_name'),language:text('language').notNull().default('en'),homePort:text('home_port'),
  targetsJson:text('targets_json'),source:text('source'),status:text('status').notNull().default('active'),
  // Inbound messages processed on messages_day (YYYY-MM-DD, America/Los_Angeles), for the OP-3 cap.
  messagesToday:integer('messages_today').notNull().default(0),messagesDay:text('messages_day'),
  lastSeenAt:text('last_seen_at').notNull(),lastErrorNoticeAt:text('last_error_notice_at'),
  createdAt:text('created_at').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[uniqueIndex('contact_phone_hash').on(t.phoneHash),uniqueIndex('contact_web_session').on(t.webSession),
  index('contact_boat').on(t.boatId),index('contact_seen').on(t.lastSeenAt)]);

// A skipper's boat. status pending -> verified/rejected by an admin (SK-4); photo
// consent is recorded with the message that gave it (SK-2). owner_contact_id is
// null once the owner has asked to be forgotten (the boat and its reports stay).
export const advisorBoats=sqliteTable('advisor_boats',{
  id:text('id').primaryKey(),slug:text('slug').notNull(),name:text('name').notNull(),landing:text('landing'),
  port:text('port').notNull(),region:text('region').notNull(),instagram:text('instagram'),bookingUrl:text('booking_url'),
  phonePublic:text('phone_public'),ownerContactId:text('owner_contact_id'),status:text('status').notNull().default('pending'),
  verifiedAt:text('verified_at'),verifiedBy:text('verified_by'),
  consentPhotosAt:text('consent_photos_at'),consentMessageId:text('consent_message_id'),consentRevokedAt:text('consent_revoked_at'),
  // SC-5: auto-publish once enough reports were confirmed without an edit.
  autoPublish:integer('auto_publish').notNull().default(0),cleanReports:integer('clean_reports').notNull().default(0),
  createdAt:text('created_at').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[uniqueIndex('boat_slug').on(t.slug),index('boat_port').on(t.port),index('boat_owner').on(t.ownerContactId)]);

// Crew who post for a boat (SK-3). Removal sets removed_at and keeps the row for audit.
export const advisorCrew=sqliteTable('advisor_crew',{
  boatId:text('boat_id').notNull(),contactId:text('contact_id').notNull(),addedBy:text('added_by').notNull(),
  addedAt:text('added_at').notNull(),removedAt:text('removed_at'),
},t=>[primaryKey({columns:[t.boatId,t.contactId]}),index('crew_contact').on(t.contactId)]);

// Every inbound and outbound message on every channel. Outbound ids are
// deterministic (sha256(in_message_id:action_index)) so a retry cannot double-send.
// body is nulled by retention after 180 days; created_by is users.id for an admin reply.
export const advisorMessages=sqliteTable('advisor_messages',{
  id:text('id').primaryKey(),contactId:text('contact_id').notNull(),direction:text('direction').notNull(),
  channel:text('channel').notNull(),providerId:text('provider_id'),body:text('body'),mediaJson:text('media_json'),
  intent:text('intent'),status:text('status').notNull(),error:text('error'),inReplyTo:text('in_reply_to'),
  tokensIn:integer('tokens_in'),tokensOut:integer('tokens_out'),createdBy:text('created_by'),
  createdAt:text('created_at').notNull(),sentAt:text('sent_at'),
},t=>[index('message_contact_time').on(t.contactId,t.createdAt),index('message_status').on(t.status),
  uniqueIndex('message_provider').on(t.channel,t.providerId)]);

// Photos, videos and audio a contact sent. The original sits in ADVISOR_MEDIA at
// r2_key (advisor/media/<contact_id>/<id>.<ext>) with EXIF already stripped;
// nothing is public unless publish_state allows it. provider_ref (0007) is the
// channel's attachment reference (BlueBubbles attachment guid, Twilio media URL)
// on a placeholder row written at the webhook, with r2_key '' until TA-C4's
// download fills it.
export const advisorMedia=sqliteTable('advisor_media',{
  id:text('id').primaryKey(),contactId:text('contact_id').notNull(),messageId:text('message_id'),boatId:text('boat_id'),
  kind:text('kind').notNull(),mime:text('mime').notNull(),bytes:integer('bytes').notNull(),
  width:integer('width'),height:integer('height'),r2Key:text('r2_key').notNull(),sha256:text('sha256').notNull(),
  exifStripped:integer('exif_stripped').notNull().default(0),classificationJson:text('classification_json'),
  hasPerson:integer('has_person'),publishState:text('publish_state').notNull().default('private'),credit:text('credit'),
  providerRef:text('provider_ref'),createdAt:text('created_at').notNull(),
},t=>[index('media_contact').on(t.contactId),index('media_publish').on(t.publishState),index('media_boat').on(t.boatId)]);

// A skipper's (or crew member's) fish report for one trip date. contact_id is
// null after "forget me": a published report is the boat's record. One draft per
// boat, day and source; a second report the same day becomes an edit (SC-4).
export const advisorReports=sqliteTable('advisor_reports',{
  id:text('id').primaryKey(),boatId:text('boat_id').notNull(),contactId:text('contact_id'),
  region:text('region').notNull(),port:text('port').notNull(),reportDate:text('report_date').notNull(),
  tripType:text('trip_type'),anglers:integer('anglers'),countsJson:text('counts_json').notNull(),
  source:text('source').notNull(),mediaId:text('media_id'),status:text('status').notNull().default('draft'),
  verified:integer('verified').notNull().default(0),notes:text('notes'),version:integer('version').notNull().default(1),
  confirmedAt:text('confirmed_at'),publishedAt:text('published_at'),
  createdAt:text('created_at').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[index('report_port_date').on(t.port,t.reportDate),index('report_boat_date').on(t.boatId,t.reportDate),
  index('report_status').on(t.status),uniqueIndex('report_boat_day_source').on(t.boatId,t.reportDate,t.source)]);

// Each correction to a report ("lings were 14"), as a list of {field, from, to}.
export const advisorReportEdits=sqliteTable('advisor_report_edits',{
  id:text('id').primaryKey(),reportId:text('report_id').notNull(),contactId:text('contact_id'),messageId:text('message_id'),
  patchJson:text('patch_json').notNull(),createdAt:text('created_at').notNull(),
},t=>[index('edit_report').on(t.reportId)]);

// The admin queue (OP-1): one row per thing needing a human. The id is
// sha256(kind:ref_id:reason)[:32], so a repeat updates rather than duplicates.
export const advisorReviews=sqliteTable('advisor_reviews',{
  id:text('id').primaryKey(),kind:text('kind').notNull(),refId:text('ref_id').notNull(),reason:text('reason').notNull(),
  status:text('status').notNull().default('open'),note:text('note'),
  openedAt:text('opened_at').notNull(),decidedAt:text('decided_at'),decidedBy:text('decided_by'),
},t=>[index('review_open').on(t.status,t.openedAt)]);

// Text Advisor answers (docs/plans/text-advisor/02-data-model.md, migration 0008).
// advisor_rules is the only source of regulations the advisor may quote (OP-6,
// principle 4). Seeded by scripts/advisor/import-rules.mjs as status 'review'
// (nothing is quotable as current until an admin marks a row 'active'); a row
// past review_due is quoted with "double-check" or not at all; 'retired' rows
// are never returned. region is a region id or '*' for the whole jurisdiction.
export const advisorRules=sqliteTable('advisor_rules',{
  id:text('id').primaryKey(),region:text('region').notNull(),jurisdiction:text('jurisdiction').notNull(),
  speciesKey:text('species_key').notNull(),speciesLabel:text('species_label').notNull(),
  sizeMinIn:real('size_min_in'),sizeMaxIn:real('size_max_in'),bagLimit:integer('bag_limit'),bagNotes:text('bag_notes'),
  seasonOpen:text('season_open'),seasonClose:text('season_close'),depthLimitFt:integer('depth_limit_ft'),
  areaNotes:text('area_notes'),gearNotes:text('gear_notes'),sourceName:text('source_name').notNull(),sourceUrl:text('source_url').notNull(),
  reviewedAt:text('reviewed_at').notNull(),reviewDue:text('review_due').notNull(),status:text('status').notNull().default('review'),
  updatedBy:text('updated_by').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[index('rule_lookup').on(t.region,t.speciesKey,t.status),index('rule_due').on(t.reviewDue)]);

// One answer per port per day (FR-1): key '<port>:<YYYY-MM-DD>', regenerated
// when inputs_hash (report ids, conditions snapshot, rules used) changes.
export const advisorDailyAnswers=sqliteTable('advisor_daily_answers',{
  key:text('key').primaryKey(),textEn:text('text_en').notNull(),textEs:text('text_es').notNull(),
  inputsHash:text('inputs_hash').notNull(),generatedAt:text('generated_at').notNull(),
});
