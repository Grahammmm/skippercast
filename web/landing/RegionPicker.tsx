import {useId, useState} from 'preact/hooks';
import {language, t, type StringId} from '../i18n.ts';
import {Button} from '../ui/Button.tsx';
import {COVERAGE_LAYERS, coverageNeedsRecheck, coverageRegionURL, coverageStatusId, lifecycleId, snapshot} from '../region-coverage.ts';

export function RegionPicker({href = location.href, now = Date.now()}: {href?: string; now?: number} = {}) {
  const initial = new URL(href).searchParams.get('region');
  const [selected, setSelected] = useState(snapshot.regions.find(r => r.id === initial)?.id ?? 'morro-bay');
  const row = snapshot.regions.find(r => r.id === selected)!;
  const lang = language.value, id = useId(), target = coverageRegionURL(href, row.id);
  return <section class="region-picker" aria-label={t('regions.choose', lang)}>
    <label for={id}>{t('regions.choose', lang)}</label>
    <select id={id} value={row.id} onChange={event => setSelected(event.currentTarget.value)} aria-describedby={`${id}-snapshot`}>
      {snapshot.regions.map(r => <option key={r.id} value={r.id}>{r.name} — {t(lifecycleId(r), lang)}</option>)}
    </select>
    <p id={`${id}-snapshot`}>{t('regions.snapshot', lang, {date: snapshot.checked_at.slice(0, 10)})}</p>
    {coverageNeedsRecheck(now) ? <p role="status">{t('regions.stale', lang)}</p> : null}
    <div aria-live="polite" aria-atomic="true" data-coverage-region={row.id}>
      <h3 lang="en">{row.name}</h3>
      <p>{t(lifecycleId(row), lang)}</p>
      <dl>{COVERAGE_LAYERS.map(layer => <div key={layer} data-coverage-layer={layer}>
        <dt>{t(`regions.${layer}` as StringId, lang)}</dt><dd>{t(coverageStatusId(row, layer), lang)}</dd>
      </div>)}</dl>
    </div>
    <Button disabled={!target} onClick={() => { if (target) location.assign(target); }}>{t(row.lifecycle === 'preview' ? 'regions.openPreview' : 'regions.open', lang)}</Button>
    <p>{t('regions.limit', lang)}</p>
    <details><summary>{t('regions.evidence', lang, {audit: snapshot.audit, revision: snapshot.source_revision.slice(0, 8)})}</summary>
      <code>{snapshot.audit_csv_sha256}</code>
    </details>
  </section>;
}
