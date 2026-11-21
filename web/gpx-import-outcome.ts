import type {SaveReport} from './gpx-import-plan.ts';
import type {GpxPreview} from './gpx-import-preview.ts';

export type GpxImportOutcome =
  | {ok: false; error: string}
  | {
    ok: true;
    saved: number;
    failed: number;
    skipped: {duplicates: number; refused: number; invalid: number; overCapacity: number};
    failedNames: string[];
  };

export function gpxImportOutcome(preview: GpxPreview, report: SaveReport | null): GpxImportOutcome {
  if (!preview.ok) return preview;

  const {counts} = preview;
  const saved = report?.saved ?? 0;
  const failed = report?.failed.length ?? 0;
  if (report !== null && saved + failed !== counts.save) return {ok: false, error: 'report-mismatch'};

  return {
    ok: true,
    saved,
    failed,
    skipped: {
      duplicates: counts.duplicates,
      refused: counts.refusedInside + counts.refusedNear + counts.refusedUnchecked,
      invalid: counts.invalid + counts.invalidPoints,
      overCapacity: counts.overCapacity,
    },
    failedNames: report?.failed.map(({name}) => name) ?? [],
  };
}
