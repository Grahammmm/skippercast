// Regional browsing envelopes communicate data gaps, never fishing grounds.
export async function initCentralCoverage(map) {
  const toggle = document.getElementById('layer-central-coverage');
  const note = document.getElementById('central-coverage-status');
  if (!toggle || !note) return;
  const centralIds = new Set(['santa-cruz-monterey-bay','monterey-point-sur','big-sur-coast',
    'south-big-sur-san-simeon','cambria-san-simeon','morro-bay','point-arguello-conception']);
  const currentRegion = new URL(location.href).searchParams.get('region') || 'morro-bay';
  if (!centralIds.has(currentRegion)) {
    toggle.closest('label').hidden = true;
    note.hidden = true;
    return;
  }
  const response = await fetch('data/central-coverage-ledger-v1.json', {signal:AbortSignal.timeout(12000)});
  if (!response.ok) throw Error('Coverage ledger unavailable');
  const ledger = await response.json();
  if (ledger.schema_version !== 1 || !Array.isArray(ledger.regions)) throw Error('Invalid coverage ledger');
  const layer = L.layerGroup();
  for (const region of ledger.regions) {
    const b = region.browsing_bounds_wgs84;
    if (!Array.isArray(b) || b.length !== 4) continue;
    const qualified = region.qualified_targets_at_or_under_200ft;
    const rectangle = L.rectangle([[b[1], b[0]], [b[3], b[2]]], {
      color: qualified ? '#117d73' : '#aa6b15',
      weight: 2, opacity: .9, fillOpacity: .035, interactive: true,
    });
    const title = document.createElement('strong');
    title.textContent = region.name;
    const detail = document.createElement('p');
    detail.textContent = qualified
      ? `${qualified} qualified surveyed candidates at or under 200 ft; none newly qualified in 200–300 ft.`
      : `No depth-qualified fishing coordinates yet. ${region.research_only_habitat_outlines} research-only habitat outlines.`;
    const caution = document.createElement('p');
    caution.textContent = 'Outline is a browsing envelope, not surveyed seabed or a fishing area.';
    const popup = document.createElement('div');
    popup.append(title, detail, caution);
    rectangle.bindPopup(popup);
    rectangle.addTo(layer);
  }
  note.textContent = `${ledger.totals.qualified_targets_at_or_under_200ft} existing surveyed targets in one package; six neighboring packages still need qualified source coverage. Orange outlines mark gaps, not reef.`;
  toggle.addEventListener('change', () => toggle.checked ? layer.addTo(map) : map.removeLayer(layer));
}
