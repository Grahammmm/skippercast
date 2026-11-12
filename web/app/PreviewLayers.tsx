// MAPLIVE-1: the owner-only "Private previews" group in the Layers rail, and its legend rows. Both render nothing
// unless the session is the owner/admin (web/map/preview-layers.ts `previewAccess`), so no visitor sees or pays for them.
// English only: the data, limits and warnings are the study's own research wording, so the group is marked lang="en".
import {PREVIEW_LAYERS, previewAccess, rampGradient, previewOn, previewStatus, togglePreview, type PreviewId, type PreviewStatus} from '../map/preview-layers.ts';
import {session} from '../account.ts';
import {RailItem} from '../ui/Rail.tsx';
import type {IconName} from '../ui/icons.tsx';

const ICON: Readonly<Record<PreviewId, IconName>> = {seafloor: 'seafloor', wind: 'wave', currents: 'current', sst: 'temperature', chlorophyll: 'map'};

const noteOf = (s: PreviewStatus | undefined): string => !s ? 'Off' : s.text;

/** The group heading and one toggle per layer; absent without the owner gate. */
/** SC1922-07: `disabledReason` (the Chart could not start) disables each toggle, keeping its choice. */
export function PreviewRailItems({disabledReason}: {disabledReason?: string} = {}) {
  void session.value;
  if (!previewAccess()) return null;
  const on = previewOn.value, status = previewStatus.value;
  return (
    <>
      <li class="app-preview-head" lang="en"><span class="ui-eyebrow">Private previews</span> <span class="ui-mono">owner only · research · not for navigation</span></li>
      {PREVIEW_LAYERS.map(l => (
        <RailItem key={l.id} id={`preview-${l.id}`} label={l.label} icon={ICON[l.id]} on={on.includes(l.id)} basis={l.basis} basisLabel={`${l.label} basis`}
          disabled={!!disabledReason} note={disabledReason ?? (on.includes(l.id) ? noteOf(status[l.id]) : l.style)} onToggle={(_, next) => togglePreview(l.id, next)} />
      ))}
    </>
  );
}

/** A legend row per preview layer that is on: its status and data time, and its colour ramp where it has one. */
export function PreviewLegendRows() {
  void session.value;
  if (!previewAccess()) return null;
  const on = previewOn.value, status = previewStatus.value;
  return (
    <>
      {PREVIEW_LAYERS.filter(l => on.includes(l.id)).map(l => {
        const s = status[l.id], gradient = s?.ramp ? rampGradient(s.ramp.colours) : null;
        return (
          <li key={l.id} class="app-legend-preview" data-preview={l.id} data-state={s?.state ?? 'loading'} lang="en">
            <span class="app-legend-preview-name">{l.label} <span class="ui-mono">preview</span></span>
            {gradient && s?.state === 'ready' ? <span class="app-preview-ramp" style={{background: gradient}} role="img" aria-label={`${l.label} colour scale, ${s.ramp!.low} to ${s.ramp!.high}`} /> : null}
            {gradient && s?.state === 'ready' ? <span class="app-preview-ends ui-mono" aria-hidden="true"><span>{s.ramp!.low}</span><span>{s.ramp!.high}</span></span> : null}
            <p class="app-legend-note" role="status">{noteOf(s)}</p>
            <p class="app-legend-note">{l.basis}</p>
          </li>
        );
      })}
    </>
  );
}
