ALTER TABLE `advisor_contacts` ADD `source_post_id` text;--> statement-breakpoint
CREATE INDEX `contact_source_post` ON `advisor_contacts` (`source_post_id`);