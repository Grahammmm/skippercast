CREATE TABLE `advisor_post_stats` (
	`post_id` text NOT NULL,
	`platform` text NOT NULL,
	`day` text NOT NULL,
	`views` integer DEFAULT 0 NOT NULL,
	`reach` integer DEFAULT 0 NOT NULL,
	`likes` integer DEFAULT 0 NOT NULL,
	`comments` integer DEFAULT 0 NOT NULL,
	`saved` integer DEFAULT 0 NOT NULL,
	`shares` integer DEFAULT 0 NOT NULL,
	`follows` integer DEFAULT 0 NOT NULL,
	`profile_visits` integer DEFAULT 0 NOT NULL,
	`link_taps` integer DEFAULT 0 NOT NULL,
	`raw_json` text NOT NULL,
	`fetched_at` text NOT NULL,
	PRIMARY KEY(`post_id`, `platform`, `day`)
);
--> statement-breakpoint
CREATE TABLE `advisor_posts` (
	`id` text PRIMARY KEY NOT NULL,
	`kind` text NOT NULL,
	`region` text NOT NULL,
	`boat_id` text,
	`media_json` text NOT NULL,
	`caption` text NOT NULL,
	`collaborators_json` text,
	`user_tags_json` text,
	`targets_json` text NOT NULL,
	`status` text DEFAULT 'draft' NOT NULL,
	`scheduled_for` text,
	`ig_container_id` text,
	`ig_media_id` text,
	`fb_post_id` text,
	`fb_story_id` text,
	`collab_status` text,
	`error` text,
	`created_by` text NOT NULL,
	`approved_by` text,
	`approved_at` text,
	`posted_at` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `post_status_time` ON `advisor_posts` (`status`,`scheduled_for`);--> statement-breakpoint
CREATE INDEX `post_boat` ON `advisor_posts` (`boat_id`);--> statement-breakpoint
ALTER TABLE `advisor_contacts` ADD `ig_sid` text;--> statement-breakpoint
CREATE UNIQUE INDEX `contact_ig_sid` ON `advisor_contacts` (`ig_sid`);