CREATE TABLE `catch_log` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`trip_id` text,
	`started_at` text NOT NULL,
	`ended_at` text,
	`method` text,
	`species` text,
	`outcome` text NOT NULL,
	`count` integer DEFAULT 0 NOT NULL,
	`lat` real,
	`lon` real,
	`note` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `catch_log_owner` ON `catch_log` (`owner`,`started_at`);