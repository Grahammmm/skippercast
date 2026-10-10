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
  readonly alerts: readonly Alert[];
  readonly missing: readonly string[];
  readonly tides: readonly TidePoint[];
  readonly tideEvents: readonly TideEvent[];
  readonly sunrise: string | null;
  readonly sunset: string | null;
}

/** The landing-reports feed rows the fleet line reads (`data` branch `regions/<id>/latest.json` `reports`). */
export interface LandingReport {readonly date: string; readonly boat: string; readonly port: string}

/** The parts of the regional daily feed (`regions/<id>/latest.json`) the regional brief reads. */
export interface RegionalDailyFeed {
  readonly region_id: string;
  readonly sources: Readonly<Record<string, RegionalSource | undefined>>;
  readonly reports?: readonly LandingReport[];
}
export interface RegionalSource {
  readonly id: string;
  readonly name: string;
  readonly kind: string;
  readonly url: string;
  readonly checked_at: string;
  readonly status: string;
  readonly data?: Record<string, unknown>;
}

/** Hourly rows of SkipperCast's regional forecast at the selected place, already sampled by the caller. */
export interface RegionalForecast {
  readonly label: string;
  readonly url: string;
  readonly issuedAt: string;
  readonly fetchedAt: string;
  readonly hours: readonly ForecastHour[];
}
