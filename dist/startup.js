// Startup helpers (P4-05): defer data a screen needs until that screen opens,
// and clear the map's loading skeleton once the first markers are drawn.
//
// navigation.js shows a screen by setting <body data-view="...">, so that
// attribute is the one signal every way of opening a screen goes through
// (tabs, links, the back button, a shared #forecast link).

/**
 * Run `work` once, the first time the `view` screen is shown (now, if it is
 * already showing). Returns a function that runs it at once instead, for
 * controls that need the data sooner (a Refresh button); calling it again is
 * harmless.
 */
export function whenView(view, work, doc = document) {
  let done = false, observer = null;
  const run = () => {
    if (done) return;
    done = true;
    observer?.disconnect();
    work();
  };
  if (doc.body?.dataset.view === view) run();
  else if (typeof MutationObserver === 'function') {
    observer = new MutationObserver(() => { if (doc.body.dataset.view === view) run(); });
    observer.observe(doc.body, {attributes: true, attributeFilter: ['data-view']});
  }
  return run;
}

/** Remove the map's loading skeleton (the map, its markers or an error now show). */
export function mapReady(doc = document) {
  const skeleton = doc.getElementById('map-loading');
  if (skeleton) skeleton.hidden = true;
  doc.querySelector('.map-wrap')?.removeAttribute('aria-busy');
}
