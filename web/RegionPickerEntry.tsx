// Rollback switch: false hides both entry points without changing any region or feed.
import type {ComponentType} from 'preact';
import {useEffect, useRef, useState} from 'preact/hooks';
import {language, t} from './i18n.ts';

export const REGION_COVERAGE_ENABLED = true;

/** Load the directory only when requested, not on the first-visit critical path. */
export function RegionPickerEntry() {
  const [Picker, setPicker] = useState<ComponentType | null>(null);
  const [failed, setFailed] = useState(false);
  const [opened, setOpened] = useState(false);
  const busy = useRef(false), alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = () => {
    if (Picker || busy.current) return;
    busy.current = true; setFailed(false);
    void import('./landing/RegionPicker.tsx').then(module => {
      if (alive.current) setPicker(() => module.RegionPicker);
    }, () => { if (alive.current) setFailed(true); }).finally(() => { busy.current = false; });
  };
  const lang = language.value;
  return REGION_COVERAGE_ENABLED ? <details class="region-picker-entry" onToggle={event => { setOpened(event.currentTarget.open); if (event.currentTarget.open) load(); }}>
    <summary style={{minHeight: 'var(--touch-min)'}}>{t('landing.regions.browse', lang)}</summary>
    {opened ? Picker ? <Picker /> : <p role="status">{t(failed ? 'landing.regions.failed' : 'landing.regions.loading', lang)}</p> : null}
  </details> : null;
}
