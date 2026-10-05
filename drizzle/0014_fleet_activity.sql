CREATE TABLE `fleet_aggregates` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`module` text NOT NULL,
	`params_json` text NOT NULL,
	`cell_id` text NOT NULL,
	`lat` real NOT NULL,
	`lon` real NOT NULL,
	`season` text NOT NULL,
	`season_part` text,
	`kind` text NOT NULL,
	`vessels_n` integer DEFAULT 0 NOT NULL,
	`events_n` integer DEFAULT 0 NOT NULL,
	`dwell_min` integer DEFAULT 0 NOT NULL,
	`first_date` text,
	`last_date` text,
	`rights` text NOT NULL,
	`computed_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `agg_lookup` ON `fleet_aggregates` (`region`,`module`,`season`,`kind`);--> statement-breakpoint
CREATE TABLE `fleet_ais_hours` (
	`region` text NOT NULL,
	`hour` text NOT NULL,
	`messages` integer DEFAULT 0 NOT NULL,
	`watched_messages` integer DEFAULT 0 NOT NULL,
	`vessels` integer DEFAULT 0 NOT NULL,
	`reconnects` integer DEFAULT 0 NOT NULL,
	`max_gap_s` integer DEFAULT 0 NOT NULL,
	`dropped` integer DEFAULT 0 NOT NULL,
	PRIMARY KEY(`region`, `hour`)
);
--> statement-breakpoint
CREATE TABLE `fleet_ais_watch` (
	`region` text NOT NULL,
	`mmsi` text NOT NULL,
	`vessel_id` text,
	`match_method` text NOT NULL,
	`confidence` real NOT NULL,
	`status` text DEFAULT 'candidate' NOT NULL,
	`ais_name` text,
	`ais_call_sign` text,
	`ais_class` text,
	`first_seen_at` text NOT NULL,
	`last_seen_at` text NOT NULL,
	`last_seen_source` text,
	`positions_30d` integer DEFAULT 0 NOT NULL,
	`updated_at` text NOT NULL,
	PRIMARY KEY(`region`, `mmsi`)
);
--> statement-breakpoint
CREATE INDEX `watch_vessel` ON `fleet_ais_watch` (`vessel_id`);--> statement-breakpoint
CREATE TABLE `fleet_events` (
	`id` text PRIMARY KEY NOT NULL,
	`trip_id` text NOT NULL,
	`segment_id` text NOT NULL,
	`vessel_id` text NOT NULL,
	`region` text NOT NULL,
	`kind` text NOT NULL,
	`lat` real NOT NULL,
	`lon` real NOT NULL,
	`radius_m` real,
	`started_at` text NOT NULL,
	`ended_at` text NOT NULL,
	`dwell_min` integer NOT NULL,
	`port_id` text,
	`vessel_class` text,
	`trip_type` text,
	`season` text NOT NULL,
	`season_part` text,
	`basis` text DEFAULT 'inferred-from-movement' NOT NULL,
	`source` text NOT NULL,
	`rights` text NOT NULL,
	`classifier_version` text NOT NULL,
	`species_json` text
);
--> statement-breakpoint
CREATE INDEX `ev_region_time` ON `fleet_events` (`region`,`started_at`);--> statement-breakpoint
CREATE INDEX `ev_vessel` ON `fleet_events` (`vessel_id`,`started_at`);--> statement-breakpoint
CREATE INDEX `ev_season` ON `fleet_events` (`region`,`season`,`kind`);--> statement-breakpoint
CREATE TABLE `fleet_segment_labels` (
	`id` text PRIMARY KEY NOT NULL,
	`trip_id` text NOT NULL,
	`started_at` text NOT NULL,
	`ended_at` text NOT NULL,
	`label` text NOT NULL,
	`labeller` text NOT NULL,
	`basis` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `label_trip` ON `fleet_segment_labels` (`trip_id`);--> statement-breakpoint
CREATE TABLE `fleet_segments` (
	`id` text PRIMARY KEY NOT NULL,
	`trip_id` text NOT NULL,
	`seq` integer NOT NULL,
	`kind` text NOT NULL,
	`started_at` text NOT NULL,
	`ended_at` text NOT NULL,
	`geometry` text,
	`points_n` integer,
	`mean_sog` real,
	`straightness` real,
	`heading_var` real
);
--> statement-breakpoint
CREATE INDEX `seg_trip` ON `fleet_segments` (`trip_id`,`seq`);--> statement-breakpoint
CREATE TABLE `fleet_trip_reports` (
	`trip_id` text NOT NULL,
	`report_kind` text NOT NULL,
	`report_ref` text NOT NULL,
	`match` text NOT NULL,
	`confidence` real NOT NULL,
	`created_at` text NOT NULL,
	PRIMARY KEY(`trip_id`, `report_kind`, `report_ref`)
);
--> statement-breakpoint
CREATE TABLE `fleet_trips` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`vessel_id` text NOT NULL,
	`mmsi` text NOT NULL,
	`depart_port_id` text,
	`return_port_id` text,
	`departed_at` text NOT NULL,
	`returned_at` text,
	`local_date` text NOT NULL,
	`season` text NOT NULL,
	`season_part` text,
	`status` text DEFAULT 'open' NOT NULL,
	`trip_type_inferred` text,
	`distance_nm` real,
	`max_offshore_nm` real,
	`fishing_min` integer,
	`positions_n` integer,
	`gap_min` integer,
	`source` text NOT NULL,
	`rights` text NOT NULL,
	`classifier_version` text NOT NULL,
	`computed_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `trip_vessel_date` ON `fleet_trips` (`vessel_id`,`local_date`);--> statement-breakpoint
CREATE INDEX `trip_region_season` ON `fleet_trips` (`region`,`season`);--> statement-breakpoint
CREATE INDEX `trip_source_time` ON `fleet_trips` (`source`,`departed_at`);