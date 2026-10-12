// Types of web/map/nearshore-model.js (FE-27): packages/coast/src/presentation.ts's own signatures.
import type {NearshoreHour, NearshoreSite} from '../../packages/coast/src/enrichment-types.ts';
import type {Report} from '../../packages/coast/src/types.ts';
/** The area's sites that are available and current: issued under 48 h ago and fetched under 3 h ago (each at most 5 min ahead). */
export declare function freshNearshore(report: Report, areaId: string, now: Date): NearshoreSite[];
/** The site's model sample nearest `at` within 90 minutes, inside its listed span and declared validity; else undefined. */
export declare function nearshoreAt(site: NearshoreSite, at: string): NearshoreHour | undefined;
/** "<site> · sample Oct 9, 3:00 PM PDT · 1h model sampling", or that no sample covers the time. */
export declare function nearshoreSampleLabel(site: NearshoreSite, hour: NearshoreHour | undefined, tz: string): string;
