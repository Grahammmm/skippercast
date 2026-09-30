// Freshness banner (guide §5.5 "Freshness pill"): says when the page is
// offline or showing saved data, and how old that data is. offline.js owns
// the host element (placed under the masthead) and the status signal; the
// wording is bannerText() in offline-core.js.
import {useLayoutEffect} from 'preact/hooks';
import {bannerText} from '../../dist/offline-core.js';
import {offlineStatus, type OfflineStatus} from '../views.ts';

function openSavedRegions() {
  // The link opens the Guide; open the offline card inside it.
  const card = document.getElementById('offline-pack-topic') as HTMLDetailsElement | null;
  if (card) { card.open = true; requestAnimationFrame(() => card.scrollIntoView({block: 'start'})); }
}

export function FreshnessBanner({host, status}: {host?: HTMLElement | null; status?: OfflineStatus}) {
  const {online, savedAt, now} = status ?? offlineStatus.value;
  const text: string | null = bannerText({online, savedAt, now: now || Date.now()});
  // Back online while saved data is still on screen: say so until a reload.
  const stale = Boolean(online && savedAt && text);
  useLayoutEffect(() => { if (host) host.hidden = !text; }, [host, text]);
  return (
    <>
      <span>{text || ''}</span>
      <a href="#guide" data-offline-guide="" onClick={openSavedRegions}>Saved regions</a>
      <button type="button" data-offline-reload="" hidden={!stale} onClick={() => location.reload()}>Reload</button>
    </>
  );
}
