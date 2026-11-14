// SCB-12: this entry has no static app imports. Start the Chart's existing
// Vite-managed library graph while the shell graph is still downloading.
// A conservative hint only: the store remains authoritative for saved homes,
// legacy links and terrain fallbacks; main.tsx warms those after URL resolution.
export function opensChart(href: string, storedPresentation: () => string | null): boolean {
  const url = new URL(href);
  if (url.pathname !== '/map' || !/^[a-z][a-z0-9-]*$/.test(url.searchParams.get('region') ?? '') || url.searchParams.has('coast')) return false;
  let mode = url.searchParams.get('presentation');
  if (mode !== 'chart' && mode !== '2d' && mode !== '3d') {
    try { mode = storedPresentation(); } catch { /* Storage can be denied. The store also defaults to Chart. */ }
  }
  return mode !== '2d' && mode !== '3d';
}

export function boot(href: string, storedPresentation: () => string | null, loadChart: () => Promise<unknown>, loadApp: () => Promise<unknown>): void {
  // Never await the hint: a failed library must not prevent the shell loading.
  // createChart owns the normal user-visible failure and retry panel.
  if (opensChart(href, storedPresentation)) void loadChart().catch(() => {});
  void loadApp();
}

if (typeof location !== 'undefined') boot(location.href, () => localStorage.getItem('skippercast-presentation-v1'),
  () => import('../map/maplibre.js'), () => import('./main.tsx'));
