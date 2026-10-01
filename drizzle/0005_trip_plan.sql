ALTER TABLE `trips` ADD `launch_point` text;--> statement-breakpoint
ALTER TABLE `trips` ADD `targets` text;--> statement-breakpoint
ALTER TABLE `trips` ADD `plan` text;--> statement-breakpoint
ALTER TABLE `trips` ADD `status` text DEFAULT 'planned' NOT NULL;--> statement-breakpoint
ALTER TABLE `trips` ADD `updated_at` text;