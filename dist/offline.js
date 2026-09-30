// Registers the service worker for every visitor (offline shell, saved data
// and trip-alert push share the stable '/sw.js'), shows an offline banner when
// saved data is on screen, offers installation, and mounts the offline trip
// pack card in the Guide.
import {installHint} from './offline-core.js';
import {offlineStatus} from '../web/views.ts';
import {track} from '../web/telemetry.ts';
import {initOfflinePack} from './offline-pack.js';

const sessionStart = Date.now();
const DISMISS = 'skippercast-install-dismissed';
let savedAt = null;

function readDismissed() {
  try { return JSON.parse(localStorage.getItem(DISMISS)) || {}; } catch { return {}; }
}
function writeDismissed(kind) {
  try { localStorage.setItem(DISMISS, JSON.stringify({...readDismissed(), [kind]: new Date().toISOString()})); } catch {}
}

// The freshness banner's host; web/components/FreshnessBanner.tsx renders its
// text, link and reload button from offlineStatus.
const banner = document.createElement('div');
banner.id = 'offline-banner';
banner.className = 'offline-banner';
banner.setAttribute('role', 'status');
banner.setAttribute('aria-live', 'polite');
banner.hidden = true;

function renderBanner() {
  const online = navigator.onLine;
  offlineStatus.value = {online, savedAt, now: Date.now()};
  document.body.classList.toggle('is-offline', !online);
}

function mountBanner() {
  const masthead = document.querySelector('.masthead');
  if (masthead) masthead.after(banner); else document.body.prepend(banner);
  renderBanner();
  setInterval(renderBanner, 60000);
  addEventListener('online', renderBanner);
  addEventListener('offline', renderBanner);
}

function registerWorker() {
  if (!('serviceWorker' in navigator) || !isSecureContext) return;
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data?.type !== 'skippercast-offline' || !event.data.savedAt) return;
    if (!savedAt || event.data.savedAt < savedAt) savedAt = event.data.savedAt;
    renderBanner();
  });
  navigator.serviceWorker.register('/sw.js').catch(error => console.warn('SkipperCast service worker not registered:', error?.message || error));
  // Ask once controlled: responses served before this listener existed still count,
  // and the worker stores this build's shell if its install could not.
  navigator.serviceWorker.ready.then(() => navigator.serviceWorker.controller?.postMessage({type: 'skippercast-offline-status'}));
  navigator.serviceWorker.addEventListener('controllerchange', () => navigator.serviceWorker.controller?.postMessage({type: 'skippercast-offline-status'}));
}

let deferredPrompt = null;
const card = document.createElement('aside');
card.className = 'install-card';
card.hidden = true;
card.setAttribute('aria-label', 'Install SkipperCast');

function standalone() {
  return matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
}

function renderInstall() {
  const hint = installHint({standalone: standalone(), promptAvailable: !!deferredPrompt, userAgent: navigator.userAgent,
    maxTouchPoints: navigator.maxTouchPoints, dismissed: readDismissed()});
  if (!hint) { card.hidden = true; return; }
  card.innerHTML = hint === 'prompt'
    ? '<div><strong>Install SkipperCast</strong><p>Open it from your home screen, with saved regions available offline.</p></div><div class="install-actions"><button type="button" class="primary" data-install>Install</button><button type="button" data-dismiss>Not now</button></div>'
    : '<div><strong>Add SkipperCast to your Home Screen</strong><p>In Safari, tap Share, then Add to Home Screen. Trip alert notifications on iPhone and iPad need it.</p></div><div class="install-actions"><button type="button" data-dismiss>Got it</button></div>';
  card.hidden = false;
  // The iOS hint is shown once per device, whether or not it is dismissed.
  if (hint === 'ios') writeDismissed('ios');
  card.querySelector('[data-dismiss]').addEventListener('click', () => { writeDismissed(hint); card.hidden = true; });
  card.querySelector('[data-install]')?.addEventListener('click', async () => {
    const prompt = deferredPrompt; deferredPrompt = null; card.hidden = true;
    if (!prompt) return;
    prompt.prompt();
    const choice = await prompt.userChoice.catch(() => null);
    if (choice?.outcome === 'dismissed') writeDismissed('prompt');
  });
}

function mountInstall() {
  const nav = document.querySelector('.app-nav');
  if (nav) nav.before(card); else document.body.append(card);
  addEventListener('beforeinstallprompt', event => { event.preventDefault(); deferredPrompt = event; renderInstall(); });
  addEventListener('appinstalled', () => { deferredPrompt = null; card.hidden = true; track('install'); });
  renderInstall();
}

registerWorker();
mountBanner();
mountInstall();
initOfflinePack(document.getElementById('offline-pack'), {sessionStart});
