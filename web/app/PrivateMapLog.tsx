import {useEffect, useState} from 'preact/hooks';
import type {ConditionsForecast} from '../conditions.ts';
import {readingSource} from '../brief/mark-forecast.ts';
import {createEntry, readEntries, saveEntry, type MapLogEntry} from '../private-map-log.ts';
import {Button} from '../ui/Button.tsx';

/** Independent of account log, trip/share state and the map's forecast-hour selector. */
export function PrivateMapLog({mark, region, forecast, tz}: {
  mark: {name: string; position?: {latitude: number; longitude: number}; withheld?: boolean};
  region: string; forecast: ConditionsForecast | null; tz: string;
}) {
  const [entries, setEntries] = useState<readonly MapLogEntry[] | null>(null), [status, setStatus] = useState('');
  const reload = () => { try { setEntries(readEntries()); } catch { setStatus('Device log unavailable. Existing records have not been changed.'); } };
  useEffect(() => { reload(); }, []);

  if (!createEntry(mark, 'catch', region, null, Date.now(), tz)) return null;
  const save = (kind: 'catch' | 'blank') => {
    const result = saveEntry(createEntry(mark, kind, region, forecast, Date.now(), tz));
    setStatus(result === 'saved' ? 'Saved on this device only.' : result === 'full' ? 'Not saved: device log is full (500 entries). Existing records are unchanged.' : 'Not saved: device storage is unavailable or unreadable.');
    if (result === 'saved') reload();
  };
  return <section class="app-mark-forecast" aria-label="Private device log">
    <p class="ui-eyebrow">Private device log</p>
    <p>Selected map position, not live GPS. Catch records a catch; blank records no catch. No species or count is inferred.</p>
    <div class="app-mark-actions">
      <Button size="sm" onClick={() => save('catch')}>Log catch here</Button>
      <Button size="sm" onClick={() => save('blank')}>Log blank here</Button>
    </div>
    <p role="status">{status}</p>
    <p>Only in this browser on this device; never uploaded or added to your account. Clearing site data loses these entries. Shared-device users can read them. NOT FOR NAVIGATION.</p>
    <details><summary>Device log ({entries?.length ?? 'unavailable'})</summary>
      <p>Conditions are model snapshots at capture time, not on-water observations. Wind and seas use the named regional forecast point. Gaps stay unavailable. <a href="/sources">Forecast sources</a></p>
      <ul>{[...(entries ?? [])].reverse().map((entry, i) => <li data-private-entry key={i}>
        <p>{entry.kind === 'catch' ? 'Catch' : 'Blank (no catch)'} · {entry.name} · {entry.region} · <time dateTime={entry.recordedAt}>{entry.recordedAt}</time></p>
        <p class="ui-mono">{entry.position.latitude.toFixed(5)}, {entry.position.longitude.toFixed(5)} · {entry.positionBasis}</p>
        {!entry.conditions ? <p>Conditions unavailable at capture time.</p> : <>
          <p>Forecast feed retrieved: {entry.conditions.retrievedAt === null ? 'unavailable' : new Date(entry.conditions.retrievedAt).toISOString()}</p>
          <ul>{[...entry.conditions.forecast.families.flatMap(f => f.rows), entry.conditions.forecast.current].map((r, j) => <li key={j}>
            {r.label}: {r.value ?? `Unavailable: ${r.gap}`} · {readingSource(r, entry.conditions!.at, tz)}
            {r.validAt !== null ? ` · Valid ${new Date(r.validAt).toISOString()}` : ''}
            {r.issuedAt !== null ? ` · Run ${new Date(r.issuedAt).toISOString()}` : ''}
          </li>)}</ul>
        </>}
      </li>)}</ul>
    </details>
  </section>;
}
