CREATE TABLE `email_links` (
	`id` text PRIMARY KEY NOT NULL,
	`email` text NOT NULL,
	`user_id` text,
	`created_at` integer NOT NULL,
	`expires_at` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `email_link_email` ON `email_links` (`email`,`created_at`);--> statement-breakpoint
CREATE INDEX `email_link_expires` ON `email_links` (`expires_at`);--> statement-breakpoint
CREATE TABLE `user_emails` (
	`email` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`verified_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `user_email_user` ON `user_emails` (`user_id`);