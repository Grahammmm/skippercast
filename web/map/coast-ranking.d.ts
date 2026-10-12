// Types of web/map/coast-ranking.js (FE-34): packages/coast's, restated because those
// modules import the renderer's readers, which web/tsconfig.json never loads.

/** The reviewed habitat properties the brief reads (packages/coast `rankedHabitat`, viewer `drawRanks`). */
export interface HabitatFeature {
  readonly id?: string | number;
  readonly type?: 'Feature';
  readonly geometry: {readonly type: string};
  readonly properties: {
    readonly id?: string; readonly region?: string; readonly waypoint_latitude: number; readonly waypoint_longitude: number;
    readonly depth_min_ft: number; readonly depth_max_ft: number; readonly terrain_score: number; readonly terrain_grade?: string;
    readonly screen_expires_at: string; readonly [field: string]: unknown;
  };
}

/** Exportable, screened, unexpired polygons with fit ≥ 2 for `field` (any when null), in fit then terrain-score order. */
export declare function rankedHabitat(features: readonly HabitatFeature[], field: string | null, now?: number): HabitatFeature[];

/** The reviewed release's admitted features and its earliest review expiry (ms); rejects when the release is unavailable. */
export declare function loadReviewedHabitat(): Promise<{features: HabitatFeature[]; expiresAt: number}>;
