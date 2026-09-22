CREATE TABLE `alert_events` (
	`id` text PRIMARY KEY NOT NULL,
	`trip_id` text NOT NULL,
	`owner` text NOT NULL,
	`kind` text NOT NULL,
	`message` text NOT NULL,
	`created_at` text NOT NULL,
	`status` text DEFAULT 'pending' NOT NULL,
	`delivered_at` text
);
--> statement-breakpoint
CREATE INDEX `event_owner_date` ON `alert_events` (`owner`,`created_at`);--> statement-breakpoint
CREATE INDEX `event_status` ON `alert_events` (`status`);--> statement-breakpoint
CREATE TABLE `comfort_feedback` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`region` text NOT NULL,
	`observed_at` text NOT NULL,
	`rating` integer NOT NULL,
	`context` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `feedback_owner` ON `comfort_feedback` (`owner`);--> statement-breakpoint
CREATE TABLE `request_limits` (
	`id` text PRIMARY KEY NOT NULL,
	`count` integer NOT NULL,
	`expires_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `delivery_receipts` (
	`id` text PRIMARY KEY NOT NULL,
	`event_id` text NOT NULL,
	`subscription_id` text NOT NULL,
	`status` text NOT NULL,
	`attempt_at` text NOT NULL,
	`http_status` integer
);
--> statement-breakpoint
CREATE INDEX `receipt_event` ON `delivery_receipts` (`event_id`);--> statement-breakpoint
CREATE TABLE `subscriptions` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`endpoint` text NOT NULL,
	`p256dh` text NOT NULL,
	`auth` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `subscription_owner` ON `subscriptions` (`owner`);--> statement-breakpoint
CREATE UNIQUE INDEX `subscription_endpoint` ON `subscriptions` (`endpoint`);--> statement-breakpoint
CREATE TABLE `trips` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`region` text NOT NULL,
	`point` text NOT NULL,
	`species` text NOT NULL,
	`date` text NOT NULL,
	`start_hour` integer NOT NULL,
	`end_hour` integer NOT NULL,
	`wind_limit` real NOT NULL,
	`gust_limit` real NOT NULL,
	`sea_limit` real NOT NULL,
	`enabled` integer DEFAULT 1 NOT NULL,
	`created_at` text NOT NULL,
	`last_assessment` text,
	`final_delivered_at` text
);
--> statement-breakpoint
CREATE INDEX `trip_owner` ON `trips` (`owner`);--> statement-breakpoint
CREATE INDEX `trip_due` ON `trips` (`enabled`,`date`);