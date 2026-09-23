const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const packets = new Map();

export async function loadPrimaryStrategies(regionId) {
  if (!/^[a-z][a-z0-9-]{1,63}$/.test(regionId)) throw new Error('Invalid region');
  if (!packets.has(regionId)) packets.set(regionId,fetch(`regions/${regionId}/strategies.json`,{signal:AbortSignal.timeout(10000)})
    .then(response => {if (!response.ok) throw new Error('Strategy unavailable');return response.json();})
    .then(packet => {if (packet.schema_version !== 1 || packet.region_id !== regionId || !packet.strategies) throw new Error('Strategy mismatch');return packet;})
    .catch(error => {packets.delete(regionId);throw error;}));
  return packets.get(regionId);
}

export function strategyMarkup(strategy, {compact=false}={}) {
  if (!strategy?.priority || !strategy.rig || !Array.isArray(strategy.find) || !Array.isArray(strategy.steps))
    return '<p>Reviewed fishing strategy unavailable for this target.</p>';
  const sources=(strategy.method_sources || []).filter(s=>s.title && /^https:\/\//.test(s.url || ''));
  const sourceLinks=sources.map(s=>`<a href="${escapeHTML(s.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(s.title)} ↗</a>`).join(' · ');
  const variants=(strategy.variants || []).map(v=>`<div><h3>${escapeHTML(v.name)}</h3><p>${escapeHTML(v.focus)} ${escapeHTML(v.presentation)}</p></div>`).join('');
  if (compact) return `<p><strong>Primary plan:</strong> ${escapeHTML(strategy.priority)}</p>${variants?`<div class="strategy-variants">${variants}</div>`:''}<p><strong>Starter rig:</strong> ${escapeHTML(strategy.rig)}</p><ol>${strategy.steps.map(s=>`<li>${escapeHTML(s)}</li>`).join('')}</ol><p><strong>Adjust:</strong> ${escapeHTML(strategy.adjust)}</p>`;
  return `<section class="primary-strategy" aria-label="Primary fishing strategy"><div class="eyebrow">PRIMARY STRATEGY · STARTER METHOD</div><p class="strategy-priority">${escapeHTML(strategy.priority)}</p>${variants?`<div class="strategy-variants">${variants}</div>`:''}<div class="strategy-grid"><div><h3>Look for</h3><ul>${strategy.find.map(s=>`<li>${escapeHTML(s)}</li>`).join('')}</ul></div><div><h3>Rig to bring</h3><p>${escapeHTML(strategy.rig)}</p></div><div><h3>On the water</h3><ol>${strategy.steps.map(s=>`<li>${escapeHTML(s)}</li>`).join('')}</ol></div><div><h3>When to change</h3><p>${escapeHTML(strategy.adjust)}</p></div></div><p class="small">A starter method, not a bite forecast or legal clearance. Open Rules for this place and date before fishing.${sourceLinks?` Method references: ${sourceLinks}.`:''}</p></section>`;
}

export async function fillPrimaryStrategy(host, regionId, speciesId) {
  const placeholder=host.querySelector('[data-primary-strategy]');
  if (!placeholder) return;
  try {
    const packet=await loadPrimaryStrategies(regionId);
    if (host.dataset.speciesEvidence !== speciesId) return;
    placeholder.innerHTML=strategyMarkup(packet.strategies[speciesId]);
  } catch {
    if (host.dataset.speciesEvidence === speciesId) placeholder.textContent='Starter method unavailable. Check the regional field notes and current regulations.';
  }
}
