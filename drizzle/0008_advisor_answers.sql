CREATE TABLE `advisor_daily_answers` (
	`key` text PRIMARY KEY NOT NULL,
	`text_en` text NOT NULL,
	`text_es` text NOT NULL,
	`inputs_hash` text NOT NULL,
	`generated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `advisor_rules` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`jurisdiction` text NOT NULL,
	`species_key` text NOT NULL,
	`species_label` text NOT NULL,
	`size_min_in` real,
	`size_max_in` real,
	`bag_limit` integer,
	`bag_notes` text,
	`season_open` text,
	`season_close` text,
	`depth_limit_ft` integer,
	`area_notes` text,
	`gear_notes` text,
	`source_name` text NOT NULL,
	`source_url` text NOT NULL,
	`reviewed_at` text NOT NULL,
	`review_due` text NOT NULL,
	`status` text DEFAULT 'review' NOT NULL,
	`updated_by` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `rule_lookup` ON `advisor_rules` (`region`,`species_key`,`status`);--> statement-breakpoint
CREATE INDEX `rule_due` ON `advisor_rules` (`review_due`);