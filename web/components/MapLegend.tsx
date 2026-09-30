// On-map legend (P4-05): a "Legend" chip at the bottom left of the map that
// opens a sheet listing the layers now visible and what their marks mean.
// A native <dialog> gives Escape, focus containment and focus return.
import type {ComponentChild} from 'preact';
import {useRef, useState} from 'preact/hooks';
import {legendEntries, type LegendEntry, type LegendState, type Swatch} from '../legend.ts';

type Assets = Record<string, string | null | undefined>;

/** Read the map's current layer choices from Map options. */
export function readLegendState(doc: Document, assets: Assets): LegendState {
  const input = (id: string) => doc.getElementById(id) as HTMLInputElement | null;
  const chosen = (id: string, none = '') => {
    const select = doc.getElementById(id) as HTMLSelectElement | null;
    return select && select.value !== none ? select.selectedOptions[0]?.textContent?.trim() || null : null;
  };
  return {
    checked: id => !!input(id)?.checked && !input(id)?.disabled,
    hasAsset: key => !!assets[key],
    weatherLayer: chosen('ocean-layer', 'none'),
    seafloorView: chosen('seafloor-view'),
    searchAreasLoaded: doc.querySelector('.search-plan-card')?.getAttribute('data-loaded') === 'true',
  };
}

const icon = (paths: ComponentChild) => (
  <svg class="legend-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
    stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>
);
const INFO = icon(<><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></>);
const CLOSE = icon(<><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>);

function swatch(id: Swatch): ComponentChild {
  if (id === 'grades') return <><span class="legend-pin A">A</span><span class="legend-pin B">B</span><span class="legend-pin C">C</span></>;
  if (id === 'cluster') return <span class="legend-cluster">5</span>;
  return <span class={`legend-mark legend-${id}`} />;
}

export function MapLegend({doc = document}: {doc?: Document}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [rows, setRows] = useState<LegendEntry[]>([]);
  const close = () => dialog.current?.close();
  async function open() {
    // region.js is loaded by boot.js before the map shows; importing it here
    // (not statically) keeps it out of this entry's chunk.
    const {getRegion} = await import('../../dist/region.js');
    setRows(legendEntries(readLegendState(doc, (getRegion().assets || {}) as Assets)));
    if (!dialog.current?.open) dialog.current?.showModal();
  }
  return <>
    <button type="button" id="map-legend-button" class="legend-chip" aria-haspopup="dialog" onClick={open}>
      {INFO}<span>Legend</span>
    </button>
    <dialog id="map-legend-sheet" class="legend-sheet" ref={dialog} aria-labelledby="map-legend-title"
      onClick={e => { if (e.target === dialog.current) close(); }}>
      <div class="legend-body">
        <div class="legend-head">
          <h2 id="map-legend-title">Map legend</h2>
          <button type="button" class="legend-close" aria-label="Close legend" onClick={close}>{CLOSE}</button>
        </div>
        <ul class="legend-list">
          {rows.map(row => (
            <li key={row.id} data-legend={row.id}>
              <span class="legend-swatch" aria-hidden="true">{swatch(row.id)}</span>
              <div>
                <strong>{row.label}</strong>
                <p>{row.text}{row.link && <> <a href={row.link.href} onClick={close}>{row.link.label}</a></>}</p>
              </div>
            </li>
          ))}
        </ul>
        <button type="button" class="legend-layers" onClick={() => { close(); (doc.getElementById('map-options') as HTMLDialogElement | null)?.showModal(); }}>
          Change map layers
        </button>
      </div>
    </dialog>
  </>;
}
