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
  const checked = Date.parse(checkedAt);
  return !Number.isFinite(now) || !Number.isFinite(checked) || now < checked || now - checked > 7 * 24 * 60 * 60 * 1000;
}
/** Only a known, published package can be opened; draft footprints never inherit the umbrella. */
export function coverageRegionURL(href: string, id: string): string | null {
  const row = snapshot.regions.find(r => r.id === id);
  return row && (row.lifecycle === 'active' || row.lifecycle === 'preview') ? regionURL(href, id) : null;
}
