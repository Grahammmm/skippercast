// Shapes of the reviewed configuration the build injects (regions/*/region.json,
// deployments/production.json) and of the D1 rows the Worker reads. Only the
// fields the Worker uses are listed.

export interface ForecastPoint {id: string; name?: string; latitude: number; longitude: number; offshore?: boolean; context?: string}
export interface MarineZones {coastal: string; offshore: string; [key: string]: string}
export interface Region {
  id: string; status?: string; timezone: string; species: string[];
  forecast_points: ForecastPoint[]; marine_zones: MarineZones;
  contexts?: Record<string, {marine_zones?: MarineZones} | undefined>;
  intelligence_feed: string; daily_feed: string; habitat_feed?: string;
  /** The jurisdictions/<id>.json whose rules apply (advisor_rules.jurisdiction). */
  jurisdiction_id?: string; landing_names?: string[];
  harbor: {information_url: string};
}
export interface Deployment {
  public_origin: string; allowed_origins: string[]; forecast_feed: string;
  scheduler: {repository: string; repository_id: string; owner_id: string; ref: string; workflow: string};
}

/** Published feeds and upstream APIs are external JSON, not yet schema-validated (P2-02). */
export type ExternalJSON = any;

export interface TripRow {
  id: string; owner: string; region: string; point: string; species: string; date: string;
  start_hour: number; end_hour: number; wind_limit: number; gust_limit: number; sea_limit: number;
  enabled: number; created_at: string; last_assessment: string | null; final_delivered_at: string | null;
  boat_name: string | null; boat_sea: number | null; boat_wind: number | null; boat_chop_period: number | null;
  launch_point: string | null; targets: string | null; plan: string | null; status: string; updated_at: string | null;
}
export interface AlertEventRow {id: string; trip_id: string; owner: string; kind: string; message: string; status: string; created_at: string; delivered_at: string | null}
export interface SubscriptionRow {id: string; owner: string; endpoint: string; p256dh: string; auth: string; created_at: string}
export interface CountRow {n: number}
