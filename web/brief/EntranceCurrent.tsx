// The Boat brief's entrance current (SC-TIDAL-1): flood, ebb or slack at the harbor entrance, when it turns, and the
// bar caution with the swell. An estimate throughout; the words and the WCOFS read are web/brief/entrance-current.ts, the
// arithmetic packages/coast entrance-current.ts. It renders inside the run line, so the desktop column and the phone sheet
// both carry it, and only for a Boat brief at a regulated bar (no brief.bar, nothing).
import type {Brief} from './types.ts';
import {Popover} from '../ui/Popover.tsx';
import {region} from '../state.ts';
import {language, t} from '../i18n.ts';
import {regionalForecast} from './Brief.tsx';
import {entranceCurrentView} from './entrance-current.ts';

export function EntranceCurrent({brief, tz, now}: {brief: Brief; tz: string; now: Date}) {
  const lang = language.value;
  const view = entranceCurrentView({brief, forecast: regionalForecast.value, region: region.value, tz, now, lang});
  if (!view) return null;
  return (
    <div class="app-entrance" role="group" aria-label={t('entrance.aria', lang)} data-band={view.band}>
      <p class="app-entrance-title ui-eyebrow">{view.title}</p>
      <p class="app-entrance-timing">{view.timing}</p>
      {view.turns ? <p class="app-entrance-turns ui-mono">{view.turns}</p> : null}
      <p class="app-entrance-caution" data-band={view.band}>{view.caution}{view.why ? ` ${view.why}` : ''}</p>
      <p class="app-entrance-wcofs">{view.wcofs}</p>
      <p class="app-entrance-foot">{view.foot} <Popover summary={t('entrance.basis.button', lang)} align="start">{view.basis}</Popover></p>
    </div>
  );
}
