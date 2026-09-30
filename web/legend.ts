// What the on-map legend lists (P4-05): the layers now visible and what their
// marks mean. The wording reuses the map's existing explanations (Map options,
// the grade guide and the layer detail sheets); change them together.
//
// Plain TypeScript with erasable syntax only, so the Node tests import it.

export type Swatch = 'mpa' | 'grades' | 'cluster' | 'habitat' | 'search' | 'drift' | 'charter' | 'commercial' | 'weather' | 'coverage' | 'seafloor';
export interface LegendEntry {id: Swatch; label: string; text: string; link?: {href: string; label: string}}

export interface LegendState {
  /** Whether a Map options layer checkbox (by element id) is on. */
  checked: (id: string) => boolean;
  /** Whether the region publishes a dataset (region.json `assets` key). */
  hasAsset: (key: string) => boolean;
  /** The weather layer's name when one is chosen (Map options), else null. */
  weatherLayer: string | null;
  /** The "Color by" choice of the seafloor layer, if any. */
  seafloorView: string | null;
  /** Whether "Where to focus" has loaded and may be outlining search areas. */
  searchAreasLoaded: boolean;
}

/** Legend rows for the map as it is now, in drawing order (top of the map first). */
export function legendEntries(s: LegendState): LegendEntry[] {
  const rows: LegendEntry[] = [{
    id: 'mpa', label: 'Protected areas (MPAs)',
    text: 'Pink boundaries, always shown. Fishing targets are excluded from every MPA. Solid outlines are State Marine Reserves; dashed outlines are other protected or closed areas.',
  }];
  if (s.checked('layer-targets') && s.hasAsset('atlas')) {
    rows.push({
      id: 'grades', label: 'Reef markers',
      text: 'A/B/C grades describe general terrain; 1–3 grades are species-specific mapped habitat fit (1 strongest), not catch odds. The color always shows the A/B/C grade.',
      link: {href: '#grade-guide', label: 'A / B / C explained'},
    });
    rows.push({id: 'cluster', label: 'Numbered circles', text: 'Count nearby reef candidates. Zoom in to separate them.'});
  }
  if (s.checked('layer-areas')) {
    if (s.hasAsset('atlas')) rows.push({id: 'habitat', label: 'Habitat outlines', text: 'Shaded footprints show part of the mapped rough habitat near a marker, at close zoom; not the entire reef.'});
    if (s.searchAreasLoaded) rows.push({id: 'search', label: 'Search areas', text: 'Areas “Where to focus” suggests investigating; fish presence unconfirmed. Dashed when conditions are incomplete.'});
  }
  if (s.checked('layer-drifts') && s.hasAsset('atlas')) rows.push({id: 'drift', label: 'Structure / drift alignments', text: 'Dashed lines follow the structure. These search geometries are not navigation routes.'});
  if (s.checked('layer-charters') && s.hasAsset('charters')) rows.push({id: 'charter', label: 'Charter-reported grounds', text: 'Purple boat labels mark charter-reported grounds; their dashed outlines are approximate search areas.'});
  if (s.checked('layer-commercial') && s.hasAsset('commercial_ais')) rows.push({id: 'commercial', label: 'Commercial AIS · 2024', text: 'Apparent fishing activity, not a verified catch spot. Depth and target species unknown.'});
  if (s.checked('layer-forecast') && s.weatherLayer) rows.push({id: 'weather', label: `Weather layer · ${s.weatherLayer}`, text: 'The chosen forecast layer at the selected hour.'});
  if (s.checked('layer-central-coverage')) rows.push({id: 'coverage', label: 'Survey evidence gaps', text: 'Central Coast source coverage. Do not infer a surveyed reef from a regional outline.'});
  if (s.checked('layer-seafloor')) rows.push({id: 'seafloor', label: 'Seafloor habitat candidates', text: s.seafloorView ? `Colored by ${s.seafloorView}.` : 'Its colors are set under Map options.'});
  return rows;
}
