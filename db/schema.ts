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
  // 0011 (TA-S0): the Instagram-scoped user id of a DM contact (09 § Inbox); unique, null for everyone else.
  igSid:text('ig_sid'),
  // 0012 (TA-S7): the post a first message came from (`[via ig:<post_id>]`, the per-post /text?s=ig&p=<post_id>
  // link, 09 § Insights), set with source on the first inbound message; counts "chats started" per post.
  sourcePostId:text('source_post_id'),
  // Inbound messages processed on messages_day (YYYY-MM-DD, America/Los_Angeles), for the OP-3 cap.
  messagesToday:integer('messages_today').notNull().default(0),messagesDay:text('messages_day'),
  lastSeenAt:text('last_seen_at').notNull(),lastErrorNoticeAt:text('last_error_notice_at'),
  createdAt:text('created_at').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[uniqueIndex('contact_phone_hash').on(t.phoneHash),uniqueIndex('contact_web_session').on(t.webSession),
  index('contact_boat').on(t.boatId),index('contact_seen').on(t.lastSeenAt),uniqueIndex('contact_ig_sid').on(t.igSid),
  index('contact_source_post').on(t.sourcePostId)]);

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
  // 0013 (CF-02, charter-fleet D5): the registry vessel this boat is, set only by an admin
  // deciding an advisor-link review (docs/plans/charter-fleet/design.md § 5); null otherwise.
  fleetVesselId:text('fleet_vessel_id'),
},t=>[uniqueIndex('boat_slug').on(t.slug),index('boat_port').on(t.port),index('boat_owner').on(t.ownerContactId),
  index('boat_fleet').on(t.fleetVesselId)]);

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
  // TA-M1 (0009): when the advisor-media job wrote advisor/derived/<id>/ (or gave up, with derived_error).
  derivedAt:text('derived_at'),derivedError:text('derived_error'),
  // 0010: the EXIF Orientation (1-8) read from a JPEG before its APP1 was stripped; null for other formats.
  orientation:integer('orientation'),
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

// Text Advisor social (docs/plans/text-advisor/02-data-model.md, 09; migration 0011).
// A post in any state: drafts (social/drafts.ts) wait for one admin approval;
// publishing (TA-S2) fills the Meta ids. media_json is the ordered advisor_media
// ids; collaborators_json up to 3 IG usernames; user_tags_json [{username,x,y}];
// targets_json the surfaces (instagram, facebook, instagram_story, facebook_story).
export const advisorPosts=sqliteTable('advisor_posts',{
  id:text('id').primaryKey(),kind:text('kind').notNull(),region:text('region').notNull(),boatId:text('boat_id'),
  mediaJson:text('media_json').notNull(),caption:text('caption').notNull(),collaboratorsJson:text('collaborators_json'),
  userTagsJson:text('user_tags_json'),targetsJson:text('targets_json').notNull(),status:text('status').notNull().default('draft'),
  scheduledFor:text('scheduled_for'),igContainerId:text('ig_container_id'),igMediaId:text('ig_media_id'),
  fbPostId:text('fb_post_id'),fbStoryId:text('fb_story_id'),collabStatus:text('collab_status'),error:text('error'),
  createdBy:text('created_by').notNull(),approvedBy:text('approved_by'),approvedAt:text('approved_at'),postedAt:text('posted_at'),
  createdAt:text('created_at').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[index('post_status_time').on(t.status,t.scheduledFor),index('post_boat').on(t.boatId)]);

// Insights per post, platform and fetch day (SP-10, TA-S7); 0 where a metric is unavailable.
export const advisorPostStats=sqliteTable('advisor_post_stats',{
  postId:text('post_id').notNull(),platform:text('platform').notNull(),day:text('day').notNull(),
  views:integer('views').notNull().default(0),reach:integer('reach').notNull().default(0),likes:integer('likes').notNull().default(0),
  comments:integer('comments').notNull().default(0),saved:integer('saved').notNull().default(0),shares:integer('shares').notNull().default(0),
  follows:integer('follows').notNull().default(0),profileVisits:integer('profile_visits').notNull().default(0),linkTaps:integer('link_taps').notNull().default(0),
  rawJson:text('raw_json').notNull(),fetchedAt:text('fetched_at').notNull(),
},t=>[primaryKey({columns:[t.postId,t.platform,t.day]})]);

// Charter fleet registry (docs/plans/charter-fleet/design.md § 5, migration 0013).
// Registry data (operator contacts, OSINT output, outreach) lives only here, never
// in git. Ids are text: sha256(...)[:32] hex where a re-run must hit the same row,
// random otherwise. Enumerated values are checked in code, not by the database.
// Stable keys (MMSI, USCG doc, state registration) are indexed but not unique: a
// conflict opens a review instead of failing an insert.

// An operator (business) running one or more vessels. user_id is a future operator
// account (US-B3); consent_revoked_at non-null means no consent from the next request (US-S3).
export const fleetOperators=sqliteTable('fleet_operators',{
  id:text('id').primaryKey(),region:text('region').notNull(),slug:text('slug').notNull(),name:text('name').notNull(),
  userId:text('user_id'),website:text('website'),phoneBusiness:text('phone_business'),emailBusiness:text('email_business'),
  bookingPlatform:text('booking_platform'),consentStatus:text('consent_status').notNull().default('unknown'),
  consentScopeJson:text('consent_scope_json'),consentRecordedAt:text('consent_recorded_at'),consentRecordedBy:text('consent_recorded_by'),
  consentRevokedAt:text('consent_revoked_at'),outreachStatus:text('outreach_status').notNull().default('none'),
  leadScore:real('lead_score'),leadScoreJson:text('lead_score_json'),
  createdAt:text('created_at').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[uniqueIndex('fo_slug').on(t.slug),index('fo_region').on(t.region),index('fo_outreach').on(t.outreachStatus)]);

// One row per vessel with the current resolved value of each field (D4). id is
// sha256(region:creation_key)[:32]; slug is also checked against advisor_boats.slug in code.
// map_display_consent (none/aggregate/named, US-C4) gates public activity layers only;
// removal_requested_at (US-C3) is kept when an admin later unhides the vessel.
export const fleetVessels=sqliteTable('fleet_vessels',{
  id:text('id').primaryKey(),region:text('region').notNull(),slug:text('slug').notNull(),
  name:text('name').notNull(),nameNorm:text('name_norm').notNull(),
  operatorId:text('operator_id'),portId:text('port_id'),landingId:text('landing_id'),
  vesselClass:text('vessel_class').notNull(),watersJson:text('waters_json').notNull(),
  uscgDoc:text('uscg_doc'),stateReg:text('state_reg'),hullId:text('hull_id'),callSign:text('call_sign'),mmsi:text('mmsi'),
  yearBuilt:integer('year_built'),passengersMax:integer('passengers_max'),bunks:integer('bunks'),
  lengthFt:real('length_ft'),beamFt:real('beam_ft'),cruiseKn:real('cruise_kn'),
  website:text('website'),bookingUrl:text('booking_url'),bookingPlatform:text('booking_platform'),
  phoneBusiness:text('phone_business'),emailBusiness:text('email_business'),
  status:text('status').notNull().default('active'),profileStatus:text('profile_status').notNull().default('listed'),
  mapDisplayConsent:text('map_display_consent').notNull().default('none'),removalRequestedAt:text('removal_requested_at'),
  pinnedJson:text('pinned_json').notNull().default('{}'),completeness:real('completeness').notNull().default(0),
  firstSeenAt:text('first_seen_at').notNull(),lastSeenAt:text('last_seen_at').notNull(),lastProfiledAt:text('last_profiled_at'),
  createdAt:text('created_at').notNull(),updatedAt:text('updated_at').notNull(),
},t=>[uniqueIndex('fv_slug').on(t.slug),index('fv_region_port').on(t.region,t.portId),index('fv_mmsi').on(t.mmsi),
  index('fv_doc').on(t.uscgDoc),index('fv_state_reg').on(t.stateReg),index('fv_name').on(t.region,t.nameNorm),
  index('fv_operator').on(t.operatorId)]);

// One row per observed value, with its provenance (all required). id is
// sha256(vessel_id|field|source_id|source_url|value_key)[:32], so re-seeing a fact
// touches it; a new scalar value from the same source sets superseded_at/by on the old row.
export const fleetVesselFacts=sqliteTable('fleet_vessel_facts',{
  id:text('id').primaryKey(),vesselId:text('vessel_id').notNull(),field:text('field').notNull(),
  valueJson:text('value_json').notNull(),valueKey:text('value_key').notNull(),
  sourceId:text('source_id').notNull(),sourceUrl:text('source_url').notNull(),method:text('method').notNull(),
  confidence:real('confidence').notNull(),rights:text('rights').notNull(),retrievedAt:text('retrieved_at').notNull(),
  firstSeenAt:text('first_seen_at').notNull(),lastSeenAt:text('last_seen_at').notNull(),
  supersededAt:text('superseded_at'),supersededBy:text('superseded_by'),runId:text('run_id').notNull(),
},t=>[index('fact_vessel_field').on(t.vesselId,t.field,t.supersededAt),index('fact_source').on(t.sourceId,t.lastSeenAt)]);

// Other names a vessel goes by (former-name, spelling, ais-name, report-name).
export const fleetAliases=sqliteTable('fleet_aliases',{
  vesselId:text('vessel_id').notNull(),aliasNorm:text('alias_norm').notNull(),alias:text('alias').notNull(),
  kind:text('kind').notNull(),sourceUrl:text('source_url'),firstSeenAt:text('first_seen_at').notNull(),lastSeenAt:text('last_seen_at').notNull(),
},t=>[primaryKey({columns:[t.vesselId,t.aliasNorm]}),index('alias_lookup').on(t.aliasNorm)]);

// A trip a vessel sells. id sha256(vessel_id|name_norm|season)[:32]; price in cents with
// its basis; season_from/to MM-DD; target_species_json holds catalog/species.json keys.
export const fleetOfferings=sqliteTable('fleet_offerings',{
  id:text('id').primaryKey(),vesselId:text('vessel_id').notNull(),name:text('name').notNull(),tripType:text('trip_type').notNull(),
  durationH:real('duration_h'),priceCents:integer('price_cents'),priceBasis:text('price_basis'),capacity:integer('capacity'),
  currency:text('currency').notNull().default('USD'),departsLocal:text('departs_local'),daysJson:text('days_json'),
  seasonFrom:text('season_from'),seasonTo:text('season_to'),targetSpeciesJson:text('target_species_json'),
  bookingUrl:text('booking_url'),status:text('status').notNull().default('active'),sourceFactIdsJson:text('source_fact_ids_json'),
  validFrom:text('valid_from'),validTo:text('valid_to'),updatedAt:text('updated_at').notNull(),
},t=>[index('offer_vessel').on(t.vesselId,t.status)]);

// Dated trips where a schedule is published. id sha256(offering_id|date|departs)[:32].
export const fleetDepartures=sqliteTable('fleet_departures',{
  id:text('id').primaryKey(),offeringId:text('offering_id').notNull(),vesselId:text('vessel_id').notNull(),date:text('date').notNull(),
  departsLocal:text('departs_local'),priceCents:integer('price_cents'),loadText:text('load_text'),
  sourceUrl:text('source_url').notNull(),retrievedAt:text('retrieved_at').notNull(),
},t=>[index('dep_vessel_date').on(t.vesselId,t.date)]);

// The fleet review queue. id sha256(kind|fingerprint)[:32]: a repeat updates, never
// duplicates; decided rows come back in the snapshot so re-runs never re-ask.
export const fleetReviews=sqliteTable('fleet_reviews',{
  id:text('id').primaryKey(),region:text('region').notNull(),kind:text('kind').notNull(),subjectId:text('subject_id'),
  candidateJson:text('candidate_json'),proposalJson:text('proposal_json'),score:real('score'),
  status:text('status').notNull().default('open'),decisionJson:text('decision_json'),decidedBy:text('decided_by'),decidedAt:text('decided_at'),
  openedAt:text('opened_at').notNull(),runId:text('run_id'),
},t=>[index('fr_open').on(t.region,t.status,t.openedAt)]);

// Detected changes (new, renamed, sold, moved, ...). id sha256(vessel_id|kind|after_json)[:32].
export const fleetChanges=sqliteTable('fleet_changes',{
  id:text('id').primaryKey(),vesselId:text('vessel_id').notNull(),kind:text('kind').notNull(),
  beforeJson:text('before_json'),afterJson:text('after_json'),detectedAt:text('detected_at').notNull(),
  runId:text('run_id'),reviewId:text('review_id'),
},t=>[index('fc_vessel').on(t.vesselId),index('fc_kind').on(t.kind,t.detectedAt)]);

// Private outreach notes and drafts (D14); body at most 8,000 characters (checked in
// code). No code path sends anything; an operator's removal request deletes these rows.
export const fleetOutreach=sqliteTable('fleet_outreach',{
  id:text('id').primaryKey(),operatorId:text('operator_id').notNull(),kind:text('kind').notNull(),channel:text('channel'),
  body:text('body').notNull(),status:text('status').notNull().default('draft'),
  createdBy:text('created_by').notNull(),createdAt:text('created_at').notNull(),approvedBy:text('approved_by'),approvedAt:text('approved_at'),
},t=>[index('out_operator').on(t.operatorId)]);

// Outbound link clicks per vessel, target, placement and day (D15). Counts only: no
// IP, user agent, user id or referrer.
export const fleetLinkClicks=sqliteTable('fleet_link_clicks',{
  vesselId:text('vessel_id').notNull(),target:text('target').notNull(),placement:text('placement').notNull(),day:text('day').notNull(),
  count:integer('count').notNull().default(0),
},t=>[primaryKey({columns:[t.vesselId,t.target,t.placement,t.day]})]);

// One row per pipeline step run or job call. id is '<run_id>:<step>'.
export const fleetRuns=sqliteTable('fleet_runs',{
  id:text('id').primaryKey(),region:text('region').notNull(),step:text('step').notNull(),sink:text('sink').notNull(),
  startedAt:text('started_at').notNull(),finishedAt:text('finished_at'),status:text('status').notNull().default('running'),
  countsJson:text('counts_json'),error:text('error'),
},t=>[index('run_region_time').on(t.region,t.startedAt)]);
