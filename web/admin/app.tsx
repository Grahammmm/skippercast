// The SkipperCast admin app (docs/plans/text-advisor/08-website.md § Admin;
// TA-W2), mounted by dist/admin.html, which the Worker serves to admins only.
// Hash-routed views: #queue and #health here; #skippers (TA-W3), #rules
// (TA-A4), #posts (TA-S1) and #funnel (TA-W4) are placeholders until their
// tasks. The relay-down banner shows on every view: health is fetched on load
// and every minute. Every string is in web/advisor/copy.ts (ADMIN_COPY).
import {render} from 'preact';
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import type {AdminView} from '../advisor/copy.ts';
import {ApiError, getHealth, when} from './api.ts';
import type {Health} from './api.ts';
import {Queue} from './queue.tsx';
import {HealthView} from './health.tsx';

export const VIEWS: readonly AdminView[] = ['queue', 'skippers', 'rules', 'posts', 'funnel', 'health'];
export const HEALTH_EVERY_MS = 60000;
const viewOf = (hash: string): AdminView => (VIEWS as readonly string[]).includes(hash.replace(/^#/, '')) ? hash.replace(/^#/, '') as AdminView : 'queue';

export function App() {
  const [view, setView] = useState<AdminView>(() => viewOf(location.hash));
  const [health, setHealth] = useState<Health | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [denied, setDenied] = useState(false);

  async function refresh(): Promise<void> {
    try { setHealth(await getHealth()); setHealthFailed(false); }
    catch (e) { setHealthFailed(true); if (e instanceof ApiError && (e.status === 401 || e.status === 404)) setDenied(true); }
  }
  useEffect(() => {
    const onHash = (): void => setView(viewOf(location.hash));
    addEventListener('hashchange', onHash);
    void refresh();
    const timer = setInterval(() => void refresh(), HEALTH_EVERY_MS);
    return () => { removeEventListener('hashchange', onHash); clearInterval(timer); };
  }, []);
  useEffect(() => { document.title = `${COPY.views[view]} · ${COPY.pageTitle}`; }, [view]);

  return (
    <>
      <header class="admin-top">
        <p class="admin-brand"><a href="/">⌁ {COPY.brand}</a></p>
        <nav aria-label={COPY.navLabel}>
          <ul>
            {VIEWS.map(v => <li key={v}><a href={`#${v}`} aria-current={v === view ? 'page' : undefined}>{COPY.views[v]}</a></li>)}
          </ul>
        </nav>
      </header>
      {health?.relay?.state === 'down' ? <p class="admin-banner" role="alert">{COPY.relayDown(when(health.relay.last_ok_at) || COPY.relayNever)}</p> : null}
      <main class="admin-main">
        {denied ? <p class="admin-error" role="alert">{COPY.signedOut}</p>
          : view === 'queue' ? <Queue />
          : view === 'health' ? <HealthView health={health} failed={healthFailed} onRefresh={() => void refresh()} />
          : (
            <section class="admin-view" aria-labelledby="placeholder-heading">
              <h1 id="placeholder-heading">{COPY.views[view]}</h1>
              <p>{COPY.placeholder(COPY.views[view])}</p>
            </section>
          )}
      </main>
    </>
  );
}

const host = typeof document === 'undefined' ? null : document.getElementById('admin-app');
if (host) { host.replaceChildren(); render(<App />, host); }
