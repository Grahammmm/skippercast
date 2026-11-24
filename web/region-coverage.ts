// SCB-16: audited availability, not live health or promotion permission.
import evidence from '../catalog/app/region-coverage.json' with {type: 'json'};
import type {StringId} from './i18n.ts';
import {regionURL} from './ports.ts';
// Compact rows follow the source's columns; common states derive only from lifecycle.
export const snapshot = {...evidence, regions: evidence.regions.map(([id, name, lifecycle, habitat, basemap]) => ({
  id: id!, name: name!, lifecycle: lifecycle!, habitat: habitat!, basemap: basemap!,
  conditions: lifecycle === 'draft' ? 'unpublished' : 'partial',
  tides: lifecycle === 'draft' ? 'unpublished' : 'predictions',
  rules: lifecycle === 'draft' ? 'unreviewed' : 'review-needed', relief: 'unconfirmed',
}))};
export type CoverageRegion = typeof snapshot.regions[number];
export const COVERAGE_LAYERS = ['conditions', 'tides', 'rules', 'basemap', 'habitat', 'relief'] as const;
export type CoverageLayer = typeof COVERAGE_LAYERS[number];

const STATUS_IDS: Record<CoverageLayer, Readonly<Record<string, StringId>>> = {
  conditions: {partial: 'regions.conditions.partial', unpublished: 'regions.unpublished'},
  tides: {predictions: 'regions.tides.predictions', unpublished: 'regions.unpublished'},
  rules: {'review-needed': 'regions.rules.review-needed', unreviewed: 'regions.rules.unreviewed'},
  basemap: {overview: 'regions.basemap.overview', 'declared-detail': 'regions.basemap.declared-detail'},
  habitat: {partial: 'regions.habitat.partial', held: 'regions.habitat.held', none: 'regions.habitat.none'},
  relief: {unconfirmed: 'regions.relief.unconfirmed'},
};
export const coverageStatusId = (row: CoverageRegion, layer: CoverageLayer): StringId =>
  STATUS_IDS[layer][row[layer]] ?? 'regions.relief.unconfirmed';
export const lifecycleId = (row: CoverageRegion): StringId =>
  row.lifecycle === 'active' ? 'regions.active' : row.lifecycle === 'preview' ? 'regions.preview' : 'regions.draft';

/** Seven days is a reminder, never an expiry that turns a held layer green. */
export function coverageNeedsRecheck(now: number, checkedAt = snapshot.checked_at): boolean {
  const checked = calendarDateExists(checkedAt) ? Date.parse(checkedAt) : NaN;
  return !Number.isFinite(now) || !Number.isFinite(checked) || now < checked || now - checked > 7 * 24 * 60 * 60 * 1000;
}
/** Date.parse rolls 2026-02-30 into March 2; an ISO-style stamp must name a day that exists. */
function calendarDateExists(stamp: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:$|T)/.exec(stamp);
  if (!m) return true; // not ISO-shaped: Date.parse alone decides, as before
  const year = +m[1]!, month = +m[2]!, day = +m[3]!;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  return days !== undefined && day >= 1 && day <= days;
}
/** Only a known, published package can be opened; draft footprints never inherit the umbrella. */
export function coverageRegionURL(href: string, id: string): string | null {
  const row = snapshot.regions.find(r => r.id === id);
  return row && (row.lifecycle === 'active' || row.lifecycle === 'preview') ? regionURL(href, id) : null;
}
