// The daily brief type (FE-31, design § 10). `web/brief/model.ts` fills it
// from packages/coast `buildDaily`, either over the coast report where one
// binds or over SkipperCast's regional feeds converted to the same report
// shape. FE-37 renders it.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {Alert, ForecastHour, TideEvent, TidePoint, Window} from '../../packages/coast/src/types.ts';
import type {DailyBrief} from '../../packages/coast/src/daily.ts';
import type {Profile} from '../profile.ts';

export type TileId = 'wind' | 'swell' | 'water' | 'tide';
/** fresh: within its limit; stale: a reading past its limit, shown with its age; unavailable: no reading. */
export type TileState = 'fresh' | 'stale' | 'unavailable';

export interface BriefTile {
  readonly id: TileId;
  readonly label: string;
  readonly value: number | null;
  readonly unit: string;
  /** One mono line under the value: gust and direction, period, observation time, datum. */
  readonly detail: string;
  /** Source label for the basis popover. */
  readonly source: string;
  readonly sourceUrl: string | null;
  /** The clock the age is measured from (issue, fetch or observation time). */
  readonly at: string | null;
  readonly ageMs: number | null;
  readonly limitMs: number;
  readonly state: TileState;
  /** The source's latest check failed and this is its last good reading (a feed `retained` source); always stale. */
  readonly lastGood?: boolean;
}

export interface BriefNotice {readonly name: string; readonly advisory: string; readonly url: string}
export interface BriefFleet {readonly count: number; readonly port: string; readonly text: string; readonly href: string}

/** Where the brief's fields came from. */
export type BriefBasis = 'coast-report' | 'regional';

export interface Brief {
  readonly basis: BriefBasis;
  readonly profile: Profile;
  readonly date: string;
  readonly label: string;
  readonly provisional: boolean;
  readonly headline: DailyBrief['headline'];
  /** The deck sentence: `buildDaily`'s summary. */
  readonly deck: DailyBrief['summary'];
  readonly status: DailyBrief['status'];
  readonly confidence: string;
  /** Wind, Swell, Water, Tide, in that order. */
  readonly tiles: readonly BriefTile[];
  /** Lower-exposure windows; never a bite window. */
  readonly windows: readonly Window[];
  /** The profile's one caveat (design § 8). */
  readonly caveat: string;
  readonly notice: BriefNotice | null;
  readonly fleet: BriefFleet | null;
  /** The local coast report line; unavailable outside a binding. */
  readonly localReport: {readonly available: boolean; readonly text: string};
  /** The spear reading (surge, clarity estimate, verdict per hour); null for the other profiles. */
  readonly spear: DailyBrief['spear'];
  /** The shore reading (surf, wind side, tide phase, verdict per hour); null for the other profiles. */
  readonly shore: DailyBrief['shore'];
  /** The harbour bar reading (ebb, swell, bar band per hour) for a boat brief at a regulated bar; null otherwise. */
  readonly bar: DailyBrief['bar'];
  /** The kayak reading (wind band and side, seas, launch surf, verdict per hour); null for the other profiles. */
  readonly kayak: DailyBrief['kayak'];
  /** The comfort limits the windows used: the profile's defaults, or the user's own (web/limits.ts) with a line saying so. */
  readonly limits: DailyBrief['limits'];
  readonly alerts: readonly Alert[];
  /** What buildDaily could not check or fill for this day (packages/coast daily.ts). */
  readonly missing: readonly string[];
  /** The feed sources behind the brief that are not ok, with their status and why (web/brief/model.ts sourceGaps). */
  readonly gaps: readonly SourceGap[];
  readonly tides: readonly TidePoint[];
  readonly tideEvents: readonly TideEvent[];
  /** The tide heights' reference level (MLLW unless the station says otherwise). */
  readonly tideDatum: string;
  readonly sunrise: string | null;
  readonly sunset: string | null;
}

/** A brief source that is not ok: stale, retained, failed or missing, kept distinct. */
export interface SourceGap {
  readonly id: string;
  /** The station or source it describes; a backup reads "NDBC 46011 (backup for 46028)". */
  readonly label: string;
  readonly status: string;
  /** One sentence: the label, the status and its age where the data has a clock. */
  readonly text: string;
}

/** The landing-reports feed rows the fleet line reads (`data` branch `regions/<id>/latest.json` `reports`). */
export interface LandingReport {readonly date: string; readonly boat: string; readonly port: string}

/** The parts of the regional daily feed (`regions/<id>/latest.json`) the regional brief reads. */
export interface RegionalDailyFeed {
  readonly region_id: string;
  readonly sources: Readonly<Record<string, RegionalSource | undefined>>;
  readonly reports?: readonly LandingReport[];
  /** The region's landing names (data branch feed); the fleet line counts only trips from these ports. */
  readonly landing_names?: readonly string[];
}
export interface RegionalSource {
  readonly id: string;
  readonly name: string;
  readonly kind: string;
  readonly url: string;
  readonly checked_at: string;
  /** ok, or degraded: stale, retained (last good data after a failed check), failed, missing. */
  readonly status: string;
  /** When the data shown was retrieved; for a retained source, its last good fetch. */
  readonly data_retrieved_at?: string;
  readonly last_success_at?: string;
  readonly data?: Record<string, unknown>;
  /** The station actually read, on configured buoy and tide roles (#554). */
  readonly station?: string;
  /** The primary station's id, present only when a backup station served the data (#554). */
  readonly fallback_for?: string;
}

/** Hourly rows of SkipperCast's regional forecast at the selected place, already sampled by the caller. */
export interface RegionalForecast {
  readonly label: string;
  readonly url: string;
  readonly issuedAt: string;
  readonly fetchedAt: string;
  readonly hours: readonly ForecastHour[];
}
