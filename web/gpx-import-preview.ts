import {MAX_GPX_BYTES, type GpxErrorCode, type GpxWaypoint, type GpxWaypointResult} from './gpx-waypoints.ts';
import type {GpxScreen} from './gpx-import-screen.ts';
import {planGpxImport} from './gpx-import-plan.ts';

export const IMPORT_CAPACITY = 100;

export function gpxFileCheck({name, size}: {name: string; size: number}): 'ok' | 'empty' | 'too-large' | 'not-gpx' {
  if (!Number.isFinite(size) || size <= 0) return 'empty';
  if (size > MAX_GPX_BYTES) return 'too-large';
  return name.toLowerCase().endsWith('.gpx') ? 'ok' : 'not-gpx';
}

export type GpxPreview =
  | {ok: false; error: GpxErrorCode | 'screen-unavailable' | 'screen-stale'}
  | {ok: true; save: GpxWaypoint[]; counts: {
    read: number;
    routePoints: number;
    invalidPoints: number;
    trackPoints: number;
    refusedInside: number;
    refusedNear: number;
    refusedUnchecked: number;
    duplicates: number;
    invalid: number;
    overCapacity: number;
    save: number;
  }};

export function gpxImportPreview(
  read: GpxWaypointResult,
  screen: GpxScreen,
  existing: readonly {lat: number; lon: number}[],
): GpxPreview {
  if (!read.ok) return {ok: false, error: read.error.code};
  if (!screen.ok) return {ok: false, error: screen.error};

  const routePoints = read.rejected.filter(point => point.reason === 'route-point-not-imported').length;
  const refused = {inside: 0, near: 0, unchecked: 0};
  for (const {reason} of screen.refused) refused[reason]++;

  const plan = planGpxImport(existing, screen.clear);
  const room = Math.max(0, IMPORT_CAPACITY - existing.length);
  const save = plan.save.slice(0, room);
  return {ok: true, save, counts: {
    read: read.waypoints.length,
    routePoints,
    invalidPoints: read.rejected.length - routePoints,
    trackPoints: read.ignoredTrackPoints,
    refusedInside: refused.inside,
    refusedNear: refused.near,
    refusedUnchecked: refused.unchecked,
    duplicates: plan.duplicates.length,
    invalid: plan.invalid.length,
    overCapacity: plan.save.length - save.length,
    save: save.length,
  }};
}
