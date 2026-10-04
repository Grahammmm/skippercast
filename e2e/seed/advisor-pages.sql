-- Seed for e2e/advisor-pages.spec.ts (TA-W1), loaded by e2e/serve.mjs after the migrations and
-- before the Worker starts, so no test writes to D1 while another reads it. The reports are dated
-- yesterday (UTC), inside every page's window wherever the run's clock is.
INSERT INTO advisor_boats(id,slug,name,landing,port,region,instagram,booking_url,status,verified_at,created_at,updated_at)
  VALUES('e2e-boat','e2e-rita-g','Rita G','Virg''s Landing','morro-bay','morro-bay','ritag','https://example.com/book','verified',datetime('now'),datetime('now'),datetime('now'));
INSERT INTO advisor_boats(id,slug,name,landing,port,region,status,created_at,updated_at)
  VALUES('e2e-wolf','e2e-sea-wolf','Sea Wolf',NULL,'morro-bay','morro-bay','pending',datetime('now'),datetime('now'));
INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,published_at,created_at,updated_at)
  VALUES('e2e-r1','e2e-boat','morro-bay','morro-bay',date('now','-1 day'),'full-day',22,'[{"label":"vermilion","species_key":"rockfish","kept":45,"released":null},{"label":"lingcod","species_key":"lingcod","kept":12,"released":2}]','count-text','published',1,2,datetime('now'),datetime('now'),datetime('now'));
INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,published_at,created_at,updated_at)
  VALUES('e2e-r2','e2e-wolf','morro-bay','morro-bay',date('now','-1 day'),'half-day',8,'[{"label":"lings","species_key":"lingcod","kept":4,"released":null}]','count-text','published',0,1,datetime('now'),datetime('now'),datetime('now'));
INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,size_min_in,bag_limit,season_open,season_close,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
  VALUES('e2e-ling','*','california-central','lingcod','Lingcod',22,2,'01-01','12-31','CDFW Ocean Sport Fishing Regulations','https://wildlife.ca.gov/Fishing/Ocean/Regulations','2026-06-01','2099-01-01','active','e2e',datetime('now'));
INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,bag_limit,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
  VALUES('e2e-rock','*','california-central','rockfish','Rockfish (RCG complex)',10,'CDFW Groundfish Summary','https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary','2026-06-01','2099-01-01','review','e2e',datetime('now'));
