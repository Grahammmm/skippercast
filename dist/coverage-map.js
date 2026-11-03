// The public coverage page reads only the published region index.
const text = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const link = row => `/map?region=${row.id}`;
const color = status => status === 'active' ? 'var(--mint)' : 'var(--amber)';

export function coverageModel(index) {
  if (!index || typeof index !== 'object' || Array.isArray(index) || !Array.isArray(index.regions)) {
    return {rows: [], error: 'unreadable'};
  }
  const rows = [];
  let skipped = 0;
  for (const region of index.regions) {
    const b = region?.fishing_bounds;
    if (typeof region?.id !== 'string' || !/^[a-z0-9-]+$/.test(region.id) ||
        typeof region.name !== 'string' || !region.name.trim() || !['active', 'preview'].includes(region.status) ||
        !Array.isArray(b) || b.length !== 4 || !b.every(Number.isFinite) ||
        b[0] < -180 || b[2] > 180 || b[1] < -90 || b[3] > 90 || b[0] >= b[2] || b[1] >= b[3]) {
      skipped++;
      continue;
    }
    rows.push({id: region.id, name: region.name, status: region.status, bounds: [...b]});
  }
  rows.sort((a, b) => b.bounds[3] - a.bounds[3]);
  return {rows, skipped};
}

export function renderMap(model, {width = 360} = {}) {
  if (model.error || !model.rows.length) return '';
  const rows = model.rows;
  const south = Math.min(...rows.map(r => r.bounds[1])) - 0.25;
  const north = Math.max(...rows.map(r => r.bounds[3])) + 0.25;
  const west = Math.min(...rows.map(r => r.bounds[0]));
  const east = Math.max(...rows.map(r => r.bounds[2]));
  const scale = (width - 100) / ((east - west) * Math.cos((north + south) / 2 * Math.PI / 180));
  const x = lon => 65 + (lon - west) * Math.cos((north + south) / 2 * Math.PI / 180) * scale;
  const y = lat => 50 + (north - lat) * scale;
  const height = y(south) + 15;
  const ticks = [];
  for (let lat = Math.ceil(south); lat <= Math.floor(north); lat++) {
    ticks.push(`<line x1="60" x2="${width - 25}" y1="${y(lat)}" y2="${y(lat)}" stroke="var(--muted)" stroke-width="0.5"/><text x="5" y="${y(lat) + 4}" fill="var(--text)">${lat}°N</text>`);
  }
  const boxes = rows.map(r => `<a href="${link(r)}"><rect class="cov-${r.status}" x="${x(r.bounds[0])}" y="${y(r.bounds[3])}" width="${x(r.bounds[2]) - x(r.bounds[0])}" height="${y(r.bounds[1]) - y(r.bounds[3])}" fill="${color(r.status)}" fill-opacity="0.65" stroke="${color(r.status)}"><title>${text(r.name)} — ${r.status}</title></rect></a>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" role="img" aria-label="Fishing bounds of published regions; details follow in the list"><rect x="5" y="5" width="12" height="12" fill="${color('active')}"/><text x="22" y="16" fill="var(--text)">Active</text><rect x="125" y="5" width="12" height="12" fill="${color('preview')}"/><text x="142" y="16" fill="var(--text)">Preview</text>${ticks.join('')}${boxes}</svg>`;
}

export function renderList(model) {
  if (model.error) return '<p>The region list could not be read. Try again later.</p>';
  const list = model.rows.length ? `<ul>${model.rows.map(r => `<li><a href="${link(r)}">${text(r.name)} — ${r.status === 'active' ? 'Active (reviewed)' : 'Preview (not fully reviewed; see its banner)'}</a></li>`).join('')}</ul>` : model.skipped ? '' : '<p>No regions are published yet.</p>';
  return list + (model.skipped ? `<p>${model.skipped} regions could not be drawn.</p>` : '');
}

async function main() {
  let index = null;
  try {
    const response = await fetch('/regions/index.json', {cache: 'no-store'});
    if (response.ok) index = await response.json();
  } catch { /* render the unreadable state */ }
  const model = coverageModel(index);
  document.getElementById('coverage-map').innerHTML = renderMap(model);
  document.getElementById('coverage-list').innerHTML = renderList(model);
}
if (typeof document !== 'undefined' && document.getElementById('coverage-map') && document.getElementById('coverage-list')) main();
