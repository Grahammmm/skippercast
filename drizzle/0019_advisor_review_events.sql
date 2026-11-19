CREATE TABLE `advisor_review_events` (
	`id` text PRIMARY KEY NOT NULL,
	`review_id` text NOT NULL,
	`kind` text NOT NULL,
	`decision` text NOT NULL,
	`actor` text NOT NULL,
	`decided_at` text,
	`intent` text,
	`followup` text,
	FOREIGN KEY (`review_id`) REFERENCES `advisor_reviews`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `review_event_review` ON `advisor_review_events` (`review_id`);