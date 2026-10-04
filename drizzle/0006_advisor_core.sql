CREATE TABLE `advisor_boats` (
	`id` text PRIMARY KEY NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`landing` text,
	`port` text NOT NULL,
	`region` text NOT NULL,
	`instagram` text,
	`booking_url` text,
	`phone_public` text,
	`owner_contact_id` text,
	`status` text DEFAULT 'pending' NOT NULL,
	`verified_at` text,
	`verified_by` text,
	`consent_photos_at` text,
	`consent_message_id` text,
	`consent_revoked_at` text,
	`auto_publish` integer DEFAULT 0 NOT NULL,
	`clean_reports` integer DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `boat_slug` ON `advisor_boats` (`slug`);--> statement-breakpoint
CREATE INDEX `boat_port` ON `advisor_boats` (`port`);--> statement-breakpoint
CREATE INDEX `boat_owner` ON `advisor_boats` (`owner_contact_id`);--> statement-breakpoint
CREATE TABLE `advisor_contacts` (
	`id` text PRIMARY KEY NOT NULL,
	`phone_hash` text,
	`phone_enc` text,
	`web_session` text,
	`channel` text NOT NULL,
	`role` text DEFAULT 'angler' NOT NULL,
	`boat_id` text,
	`display_name` text,
	`language` text DEFAULT 'en' NOT NULL,
	`home_port` text,
	`targets_json` text,
	`source` text,
	`status` text DEFAULT 'active' NOT NULL,
	`messages_today` integer DEFAULT 0 NOT NULL,
	`messages_day` text,
	`last_seen_at` text NOT NULL,
	`last_error_notice_at` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `contact_phone_hash` ON `advisor_contacts` (`phone_hash`);--> statement-breakpoint
CREATE UNIQUE INDEX `contact_web_session` ON `advisor_contacts` (`web_session`);--> statement-breakpoint
CREATE INDEX `contact_boat` ON `advisor_contacts` (`boat_id`);--> statement-breakpoint
CREATE INDEX `contact_seen` ON `advisor_contacts` (`last_seen_at`);--> statement-breakpoint
CREATE TABLE `advisor_crew` (
	`boat_id` text NOT NULL,
	`contact_id` text NOT NULL,
	`added_by` text NOT NULL,
	`added_at` text NOT NULL,
	`removed_at` text,
	PRIMARY KEY(`boat_id`, `contact_id`)
);
--> statement-breakpoint
CREATE INDEX `crew_contact` ON `advisor_crew` (`contact_id`);--> statement-breakpoint
CREATE TABLE `advisor_media` (
	`id` text PRIMARY KEY NOT NULL,
	`contact_id` text NOT NULL,
	`message_id` text,
	`boat_id` text,
	`kind` text NOT NULL,
	`mime` text NOT NULL,
	`bytes` integer NOT NULL,
	`width` integer,
	`height` integer,
	`r2_key` text NOT NULL,
	`sha256` text NOT NULL,
	`exif_stripped` integer DEFAULT 0 NOT NULL,
	`classification_json` text,
	`has_person` integer,
	`publish_state` text DEFAULT 'private' NOT NULL,
	`credit` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `media_contact` ON `advisor_media` (`contact_id`);--> statement-breakpoint
CREATE INDEX `media_publish` ON `advisor_media` (`publish_state`);--> statement-breakpoint
CREATE INDEX `media_boat` ON `advisor_media` (`boat_id`);--> statement-breakpoint
CREATE TABLE `advisor_messages` (
	`id` text PRIMARY KEY NOT NULL,
	`contact_id` text NOT NULL,
	`direction` text NOT NULL,
	`channel` text NOT NULL,
	`provider_id` text,
	`body` text,
	`media_json` text,
	`intent` text,
	`status` text NOT NULL,
	`error` text,
	`in_reply_to` text,
	`tokens_in` integer,
	`tokens_out` integer,
	`created_by` text,
	`created_at` text NOT NULL,
	`sent_at` text
);
--> statement-breakpoint
CREATE INDEX `message_contact_time` ON `advisor_messages` (`contact_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `message_status` ON `advisor_messages` (`status`);--> statement-breakpoint
CREATE UNIQUE INDEX `message_provider` ON `advisor_messages` (`channel`,`provider_id`);--> statement-breakpoint
CREATE TABLE `advisor_report_edits` (
	`id` text PRIMARY KEY NOT NULL,
	`report_id` text NOT NULL,
	`contact_id` text,
	`message_id` text,
	`patch_json` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `edit_report` ON `advisor_report_edits` (`report_id`);--> statement-breakpoint
CREATE TABLE `advisor_reports` (
	`id` text PRIMARY KEY NOT NULL,
	`boat_id` text NOT NULL,
	`contact_id` text,
	`region` text NOT NULL,
	`port` text NOT NULL,
	`report_date` text NOT NULL,
	`trip_type` text,
	`anglers` integer,
	`counts_json` text NOT NULL,
	`source` text NOT NULL,
	`media_id` text,
	`status` text DEFAULT 'draft' NOT NULL,
	`verified` integer DEFAULT 0 NOT NULL,
	`notes` text,
	`version` integer DEFAULT 1 NOT NULL,
	`confirmed_at` text,
	`published_at` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `report_port_date` ON `advisor_reports` (`port`,`report_date`);--> statement-breakpoint
CREATE INDEX `report_boat_date` ON `advisor_reports` (`boat_id`,`report_date`);--> statement-breakpoint
CREATE INDEX `report_status` ON `advisor_reports` (`status`);--> statement-breakpoint
CREATE UNIQUE INDEX `report_boat_day_source` ON `advisor_reports` (`boat_id`,`report_date`,`source`);--> statement-breakpoint
CREATE TABLE `advisor_reviews` (
	`id` text PRIMARY KEY NOT NULL,
	`kind` text NOT NULL,
	`ref_id` text NOT NULL,
	`reason` text NOT NULL,
	`status` text DEFAULT 'open' NOT NULL,
	`note` text,
	`opened_at` text NOT NULL,
	`decided_at` text,
	`decided_by` text
);
--> statement-breakpoint
CREATE INDEX `review_open` ON `advisor_reviews` (`status`,`opened_at`);--> statement-breakpoint
ALTER TABLE `users` ADD `role` text;