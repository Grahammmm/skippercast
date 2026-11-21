import {signal} from '@preact/signals';

type View = typeof import('./Reports.tsx').Reports;
type LoadState = {view: View} | {error: unknown} | null;

export function createLazyReports(load: () => Promise<{Reports: View}>) {
  const state = signal(null as LoadState);
  // Shared by both shells, including when one unmounts during the import.
  let pending: Promise<void> | undefined;

  return function LazyReports(props: Parameters<View>[0]) {
    const result = state.value;
    if (result === null) {
      pending ??= load().then(({Reports}) => { state.value = {view: Reports}; }, error => {
        pending = undefined;
        state.value = {error};
      });
      return <article class="app-reports" />;
    }
    // Throw in render so the shell's existing Guard handles the load failure.
    if ('error' in result) {
      state.value = null;
      throw result.error;
    }
    return <result.view {...props} />;
  };
}

export const LazyReports = createLazyReports(() => import('./Reports.tsx'));