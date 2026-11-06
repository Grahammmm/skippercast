// Fleet view (FE-53, docs/plans/front-end/design.md § 6 and § 9): the home of
// v1's fleet controls. It takes the brief column's place on the desktop and the
// sheet's on a phone, so the map it drives stays in view.
//
// Public part: the charter grounds (the Charter fleet rail entry, `?layers=fleet`)
// with their status and basis sentence, the entry's Commercial AIS 2024 option
// where the region has the file, and the boat directory link while the public
// port pages answer (web/fleet.ts). No boat is named here.
//
// Admin part, only once the server admitted the viewer (v1's `fleetAccess`
// through web/map/fleet.ts: /api/session says admin, then the admin-only filters
// probe, a 404 while FLEET_ENABLED or FLEET_MAP_ENABLED is off): v1's filter
// form (dist/index.html `#fleet-filters`), the three activity layers, the
// planning-only checkbox, v1's status line and how the activity is inferred.
// "Apply filters" sets `activityFilters`, which FE-24's layers send to the map
// API with v1's own query builder; "Show on map" also turns the events layer on
// when no activity layer is, as v1's button does.
import {useEffect, useState} from 'preact/hooks';
import {boatDirectory, directoryHref} from '../../fleet.ts';
import {language, t, type Language} from '../../i18n.ts';
import {groundsState} from '../../map/charter-grounds.ts';
import {aisOn, aisState} from '../../map/commercial-ais.ts';
import {activityAccess} from '../../map/fleet.ts';
import {layerCopy, layerEntry} from '../../map/layers.ts';
import {savedPortId, type Port} from '../../ports.ts';
import {layers, region} from '../../state.ts';
import {EnglishDetail} from '../EnglishDetail.tsx';
import {Admin, Check, showGrounds} from './FleetAdmin.tsx';

export {ACTIVITY_OFF} from './FleetAdmin.tsx';

/** A layer's basis in the page's language: English shows the registry's runtime basis as it is; Spanish leads with the registry sentence in Spanish, then the runtime basis unchanged (labelled English) unless it is the registry's own English sentence. */
function Basis({id, lang}: {id: string; lang: Language}) {
  const runtime = layerEntry(id).basis;
  if (lang !== 'es') return <p class="app-fleet-basis">{runtime}</p>;
  return <p class="app-fleet-basis">{layerCopy(id, lang).basis}{runtime && runtime !== layerCopy(id, 'en').basis ? <> <EnglishDetail lang={lang}>{runtime}</EnglishDetail></> : null}</p>;
}

/** The public part: grounds, the AIS option and the directory link. */
export function Public({directory}: {directory: readonly Port[]}) {
  const lang = language.value, on = layers.value.includes('fleet'), grounds = groundsState.value, ais = aisState.value;
  // The layer's own note is English text it wrote at run time: whole, labelled English in Spanish.
  const status = !on ? t('fleet.public.off', lang) : grounds.drawn ? t(grounds.drawn === 1 ? 'fleet.public.drawn.one' : 'fleet.public.drawn.other', lang, {n: grounds.drawn}) : <EnglishDetail lang={lang}>{grounds.note}</EnglishDetail>;
  return (
    <>
      <h2 class="ui-eyebrow">{t('fleet.public.grounds', lang)}</h2>
      <Check label={t('fleet.public.show', lang)} on={on} onChange={showGrounds} />
      <p class="app-empty" role="status">{status}{grounds.audit ? t('fleet.public.audited', lang, {date: grounds.audit}) : ''}</p>
      <Basis id="charter-grounds" lang={lang} />
      {ais.offered ? (
        <>
          <Check label={layerCopy('commercial-ais', lang).label} on={on && aisOn.value} onChange={next => { aisOn.value = next; if (next && !on) showGrounds(true); }} />
          {on && aisOn.value && ais.note ? <p class="app-empty"><EnglishDetail lang={lang}>{ais.note}</EnglishDetail></p> : null}
          <Basis id="commercial-ais" lang={lang} />
        </>
      ) : null}
      {directory.length ? (
        <>
          <h2 class="ui-eyebrow">{t('fleet.public.directory', lang)}</h2>
          <ul class="app-fleet-links">{directory.map(p => <li key={p.id}><a href={directoryHref(p)}>{t('fleet.public.boatsOut', lang, {port: p.name})}</a></li>)}</ul>
        </>
      ) : null}
    </>
  );
}

/** The Fleet view; `onShowMap` lets the phone lower its sheet after "Show on map". */
export function Fleet({onShowMap}: {onShowMap?: () => void} = {}) {
  const id = region.value;
  const [directory, setDirectory] = useState<{region: string | null; ports: readonly Port[]}>({region: null, ports: []});
  useEffect(() => {
    let live = true;
    void boatDirectory(id, savedPortId()).then(ports => { if (live) setDirectory({region: id, ports}); });
    return () => { live = false; };
  }, [id]);
  return (
    // Not a landmark of its own: the desktop's aside and the phone's sheet are already labelled "Fleet".
    <div class="app-fleet">
      <h1 id="app-fleet-title">{t('shell.view.fleet', language.value)}</h1>
      <Public directory={directory.region === id ? directory.ports : []} />
      {activityAccess.value ? <Admin onShowMap={onShowMap} /> : null}
    </div>
  );
}
