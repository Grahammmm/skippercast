CREATE TABLE `fleet_aliases` (
	`vessel_id` text NOT NULL,
	`alias_norm` text NOT NULL,
	`alias` text NOT NULL,
	`kind` text NOT NULL,
	`source_url` text,
	`first_seen_at` text NOT NULL,
	`last_seen_at` text NOT NULL,
	PRIMARY KEY(`vessel_id`, `alias_norm`)
);
--> statement-breakpoint
CREATE INDEX `alias_lookup` ON `fleet_aliases` (`alias_norm`);--> statement-breakpoint
CREATE TABLE `fleet_changes` (
	`id` text PRIMARY KEY NOT NULL,
	`vessel_id` text NOT NULL,
	`kind` text NOT NULL,
	`before_json` text,
	`after_json` text,
	`detected_at` text NOT NULL,
	`run_id` text,
	`review_id` text
);
--> statement-breakpoint
CREATE INDEX `fc_vessel` ON `fleet_changes` (`vessel_id`);--> statement-breakpoint
CREATE INDEX `fc_kind` ON `fleet_changes` (`kind`,`detected_at`);--> statement-breakpoint
CREATE TABLE `fleet_departures` (
	`id` text PRIMARY KEY NOT NULL,
	`offering_id` text NOT NULL,
	`vessel_id` text NOT NULL,
	`date` text NOT NULL,
	`departs_local` text,
	`price_cents` integer,
	`load_text` text,
	`source_url` text NOT NULL,
	`retrieved_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `dep_vessel_date` ON `fleet_departures` (`vessel_id`,`date`);--> statement-breakpoint
CREATE TABLE `fleet_link_clicks` (
	`vessel_id` text NOT NULL,
	`target` text NOT NULL,
	`placement` text NOT NULL,
	`day` text NOT NULL,
	`count` integer DEFAULT 0 NOT NULL,
	PRIMARY KEY(`vessel_id`, `target`, `placement`, `day`)
);
--> statement-breakpoint
CREATE TABLE `fleet_offerings` (
	`id` text PRIMARY KEY NOT NULL,
	`vessel_id` text NOT NULL,
	`name` text NOT NULL,
	`trip_type` text NOT NULL,
	`duration_h` real,
	`price_cents` integer,
	`price_basis` text,
	`capacity` integer,
	`currency` text DEFAULT 'USD' NOT NULL,
	`departs_local` text,
	`days_json` text,
	`season_from` text,
	`season_to` text,
	`target_species_json` text,
	`booking_url` text,
	`status` text DEFAULT 'active' NOT NULL,
	`source_fact_ids_json` text,
	`valid_from` text,
	`valid_to` text,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `offer_vessel` ON `fleet_offerings` (`vessel_id`,`status`);--> statement-breakpoint
CREATE TABLE `fleet_operators` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`user_id` text,
	`website` text,
	`phone_business` text,
	`email_business` text,
	`booking_platform` text,
	`consent_status` text DEFAULT 'unknown' NOT NULL,
	`consent_scope_json` text,
	`consent_recorded_at` text,
	`consent_recorded_by` text,
	`consent_revoked_at` text,
	`outreach_status` text DEFAULT 'none' NOT NULL,
	`lead_score` real,
	`lead_score_json` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `fo_slug` ON `fleet_operators` (`slug`);--> statement-breakpoint
CREATE INDEX `fo_region` ON `fleet_operators` (`region`);--> statement-breakpoint
CREATE INDEX `fo_outreach` ON `fleet_operators` (`outreach_status`);--> statement-breakpoint
CREATE TABLE `fleet_outreach` (
	`id` text PRIMARY KEY NOT NULL,
	`operator_id` text NOT NULL,
	`kind` text NOT NULL,
	`channel` text,
	`body` text NOT NULL,
	`status` text DEFAULT 'draft' NOT NULL,
	`created_by` text NOT NULL,
	`created_at` text NOT NULL,
	`approved_by` text,
	`approved_at` text
);
--> statement-breakpoint
CREATE INDEX `out_operator` ON `fleet_outreach` (`operator_id`);--> statement-breakpoint
CREATE TABLE `fleet_reviews` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`kind` text NOT NULL,
	`subject_id` text,
	`candidate_json` text,
	`proposal_json` text,
	`score` real,
	`status` text DEFAULT 'open' NOT NULL,
	`decision_json` text,
	`decided_by` text,
	`decided_at` text,
	`opened_at` text NOT NULL,
	`run_id` text
);
--> statement-breakpoint
CREATE INDEX `fr_open` ON `fleet_reviews` (`region`,`status`,`opened_at`);--> statement-breakpoint
CREATE TABLE `fleet_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`step` text NOT NULL,
	`sink` text NOT NULL,
	`started_at` text NOT NULL,
	`finished_at` text,
	`status` text DEFAULT 'running' NOT NULL,
	`counts_json` text,
	`error` text
);
--> statement-breakpoint
CREATE INDEX `run_region_time` ON `fleet_runs` (`region`,`started_at`);--> statement-breakpoint
CREATE TABLE `fleet_vessel_facts` (
	`id` text PRIMARY KEY NOT NULL,
	`vessel_id` text NOT NULL,
	`field` text NOT NULL,
	`value_json` text NOT NULL,
	`value_key` text NOT NULL,
	`source_id` text NOT NULL,
	`source_url` text NOT NULL,
	`method` text NOT NULL,
	`confidence` real NOT NULL,
	`rights` text NOT NULL,
	`retrieved_at` text NOT NULL,
	`first_seen_at` text NOT NULL,
	`last_seen_at` text NOT NULL,
	`superseded_at` text,
	`superseded_by` text,
	`run_id` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `fact_vessel_field` ON `fleet_vessel_facts` (`vessel_id`,`field`,`superseded_at`);--> statement-breakpoint
CREATE INDEX `fact_source` ON `fleet_vessel_facts` (`source_id`,`last_seen_at`);--> statement-breakpoint
CREATE TABLE `fleet_vessels` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`name_norm` text NOT NULL,
	`operator_id` text,
	`port_id` text,
	`landing_id` text,
	`vessel_class` text NOT NULL,
	`waters_json` text NOT NULL,
	`uscg_doc` text,
	`state_reg` text,
	`hull_id` text,
	`call_sign` text,
	`mmsi` text,
	`year_built` integer,
	`passengers_max` integer,
	`bunks` integer,
	`length_ft` real,
	`beam_ft` real,
	`cruise_kn` real,
	`website` text,
	`booking_url` text,
	`booking_platform` text,
	`phone_business` text,
	`email_business` text,
	`status` text DEFAULT 'active' NOT NULL,
	`profile_status` text DEFAULT 'listed' NOT NULL,
	`map_display_consent` text DEFAULT 'none' NOT NULL,
	`removal_requested_at` text,
	`pinned_json` text DEFAULT '{}' NOT NULL,
	`completeness` real DEFAULT 0 NOT NULL,
	`first_seen_at` text NOT NULL,
	`last_seen_at` text NOT NULL,
	`last_profiled_at` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `fv_slug` ON `fleet_vessels` (`slug`);--> statement-breakpoint
CREATE INDEX `fv_region_port` ON `fleet_vessels` (`region`,`port_id`);--> statement-breakpoint
CREATE INDEX `fv_mmsi` ON `fleet_vessels` (`mmsi`);--> statement-breakpoint
CREATE INDEX `fv_doc` ON `fleet_vessels` (`uscg_doc`);--> statement-breakpoint
CREATE INDEX `fv_state_reg` ON `fleet_vessels` (`state_reg`);--> statement-breakpoint
CREATE INDEX `fv_name` ON `fleet_vessels` (`region`,`name_norm`);--> statement-breakpoint
CREATE INDEX `fv_operator` ON `fleet_vessels` (`operator_id`);--> statement-breakpoint
ALTER TABLE `advisor_boats` ADD `fleet_vessel_id` text;--> statement-breakpoint
CREATE INDEX `boat_fleet` ON `advisor_boats` (`fleet_vessel_id`);