/// <reference types="vite/client" />
// CoastMarkup (FE-75, docs/plans/front-end/design.md § 3A.2): the v2 host for
// the escaped HTML and SVG strings that packages/coast renders. v2 reuses those
// renderers and never forks them, so their output has to reach the DOM as
// markup. The allow-list starts with charts/series.ts `chart`; the brief's
// tide sparkline (FE-33) calls `chart` with briefing.ts `tideChart`'s
// arguments (web/tides.ts) rather than adding `tideChart`. `historyView`,
// `catchSheet` and `fleetBrief` join it with the task that first mounts
// them (FE-35, Reports): their modules do not yet
// type-check under web/tsconfig.json's noUncheckedIndexedAccess, and fixing
// that is a packages/coast change announced on issue #413.
//
// Trust boundary. This is the one file in web/ that may write markup into the
// DOM (scripts/check_web.py fails on innerHTML and the other sinks anywhere
// else). It assigns only the string that a renderer in COAST_RENDERERS
// returns: the prop names the renderer, the host never passes a function or a
// string, and an unknown name throws. Those renderers escape every
// feed-derived value with packages/coast's `escapeHTML`. The one value `chart`
// interpolates unescaped, `Series.color`, must pass `isCoastColour` (a hex,
// rgb()/hsl() or var(--name) colour) or the call throws, so an attribute
// break-out never reaches the DOM; pass a token such as 'var(--coast-blue)'.
// Adding a renderer here means reading it for unescaped values and guarding
// them the same way.
//
// The string mounts in a shadow root with panel.css and the token bridge, and
// the host carries data-coast-theme="tokens", so packages/coast's
// var(--coast-…, literal) colours read web/tokens.css (§ 3A.4). panel.css
// declares no custom property of its own (FE-77), so nothing in the shadow
// root shadows the web/tokens.css names the bridge reads. Clicks on the
// renderers' controls and drags on a `chart` come back as typed callbacks.
import {useLayoutEffect, useRef} from 'preact/hooks';
import panelStyles from '../../packages/coast/panel.css?url';
import bridgeStyles from '../../packages/coast/tokens-bridge.css?url';
import {chart} from '../../packages/coast/src/charts/series.ts';
import {hourParam} from '../state.ts';

/** The allow-list: the only functions whose output this host mounts. */
export const COAST_RENDERERS = Object.freeze({chart});
export type CoastRendererName = keyof typeof COAST_RENDERERS;
export type CoastArgs<K extends CoastRendererName> = Parameters<(typeof COAST_RENDERERS)[K]>;

const COLOUR = /^(?:#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|(?:rgb|hsl)a?\([\d\s.,%/+-]+\)|var\(--[\w-]+\))$/;
/** A colour `chart()` may write into a `style` attribute: hex, rgb()/hsl() with numbers only, or var(--name). */
export const isCoastColour = (value: unknown): value is string => typeof value === 'string' && COLOUR.test(value);

/** The markup an allow-listed renderer returns for `args`; any other name, or an unsafe colour, throws. */
export function coastMarkup<K extends CoastRendererName>(renderer: K, args: CoastArgs<K>): string {
  if (!Object.hasOwn(COAST_RENDERERS, renderer)) throw new TypeError(`Not a packages/coast renderer: ${String(renderer)}`);
  if (renderer === 'chart') {
    const rows: unknown = (args as CoastArgs<'chart'>)[0];
    if (!Array.isArray(rows) || !rows.every(row => isCoastColour((row as {color?: unknown} | null)?.color))) throw new TypeError('chart() series colours must be a hex, RGB, HSL or custom-property colour');
  }
  const render = COAST_RENDERERS[renderer] as (...input: CoastArgs<K>) => string;
  return render(...args);
}

/** `chart()`'s horizontal layout in viewBox units (tests/test_coast_markup.mjs pins these to its output). */
export const CHART_GEOMETRY = {width: 840, left: 69, right: 32, miniLeft: 0, miniRight: 0} as const;
const HOUR_MS = 3_600_000;

/** The whole UTC hour ("2026-10-05T20:00Z") nearest viewBox x `x` on a `chart(…, start, end, …)`; null outside a span of one hour or more. */
export function chartHourAt(x: number, start: string, end: string, mini = false): string | null {
  const g = CHART_GEOMETRY, left = mini ? g.miniLeft : g.left, right = mini ? g.miniRight : g.right;
  const t0 = Date.parse(start), t1 = Date.parse(end);
  if (!Number.isFinite(x) || !Number.isFinite(t0) || !Number.isFinite(t1)) return null;
  const first = Math.ceil(t0 / HOUR_MS) * HOUR_MS, last = Math.floor(t1 / HOUR_MS) * HOUR_MS;
  if (last < first) return null;
  const fraction = Math.min(1, Math.max(0, (x - left) / (g.width - left - right)));
  const at = Math.min(last, Math.max(first, Math.round((t0 + fraction * (t1 - t0)) / HOUR_MS) * HOUR_MS));
  return hourParam(at / 1000);
}

/** A choice made on a renderer's own controls. */
export type CoastSelection = {readonly name: 'history-days' | 'history-station' | 'history-metric' | 'open' | 'day'; readonly value: string};
const CLICKS = [['data-history-days', 'history-days'], ['data-open', 'open'], ['data-day', 'day']] as const;
const CHANGES = {'history-station': 'history-station', 'history-metric': 'history-metric'} as const;

/** The selection a click on `target` makes, if it lands on one of the renderers' controls. */
export function clickSelection(target: Pick<Element, 'closest'>): CoastSelection | null {
  for (const [attribute, name] of CLICKS) {
    const value = target.closest(`[${attribute}]`)?.getAttribute(attribute);
    if (value != null) return {name, value};
  }
  return null;
}

/** The selection a change on `target` makes (the history station and measurement pickers). */
export function changeSelection(target: {readonly id: string; readonly value?: unknown}): CoastSelection | null {
  const name = Object.hasOwn(CHANGES, target.id) ? CHANGES[target.id as keyof typeof CHANGES] : null;
  return name && typeof target.value === 'string' ? {name, value: target.value} : null;
}

export type CoastMarkupProps<K extends CoastRendererName> = {
  readonly renderer: K;
  readonly args: CoastArgs<K>;
  readonly class?: string;
  /** `chart` only: the hour under the pointer while it is pressed. */
  readonly onCursor?: (hour: string) => void;
  readonly onSelect?: (selection: CoastSelection) => void;
};

/** Mount `renderer(...args)` in a token-bridged shadow root; re-renders when the markup changes. */
export function CoastMarkup<K extends CoastRendererName>(props: CoastMarkupProps<K>) {
  const host = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement | null>(null);
  const shown = useRef<string | null>(null);
  const latest = useRef(props);
  latest.current = props;
  const markup = coastMarkup(props.renderer, props.args);

  useLayoutEffect(() => {
    const element = host.current;
    if (!element) return;
    const root = element.shadowRoot ?? element.attachShadow({mode: 'open'});
    const sheets = [panelStyles, bridgeStyles].map(href => Object.assign(document.createElement('link'), {rel: 'stylesheet', href}));
    const content = document.createElement('div');
    content.className = 'coast-markup';
    root.replaceChildren(...sheets, content);
    body.current = content;
    shown.current = null;
    // A press on the chart starts a drag; the pointer is captured, so moves are read against the chart itself.
    let dragging = false;
    const cursor = (event: PointerEvent) => {
      const {renderer, args, onCursor} = latest.current;
      const svg = content.querySelector('svg.series-chart');
      const matrix = svg instanceof SVGSVGElement ? svg.getScreenCTM() : null;
      if (!dragging || renderer !== 'chart' || !onCursor || !matrix) return;
      const [, start, end, , , options] = args as CoastArgs<'chart'>;
      const hour = chartHourAt(new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()).x, start, end, !!options?.mini);
      if (hour) onCursor(hour);
    };
    const press = (event: PointerEvent) => {
      if (latest.current.renderer !== 'chart' || !latest.current.onCursor || !(event.target instanceof Element) || !event.target.closest('svg.series-chart')) return;
      dragging = true;
      content.setPointerCapture?.(event.pointerId);
      cursor(event);
    };
    const release = () => { dragging = false; };
    const click = (event: Event) => {
      const selection = event.target instanceof Element ? clickSelection(event.target) : null;
      if (selection) latest.current.onSelect?.(selection);
    };
    const change = (event: Event) => {
      const selection = event.target instanceof HTMLSelectElement ? changeSelection(event.target) : null;
      if (selection) latest.current.onSelect?.(selection);
    };
    content.addEventListener('pointerdown', press);
    content.addEventListener('pointermove', cursor);
    content.addEventListener('pointerup', release);
    content.addEventListener('pointercancel', release);
    content.addEventListener('click', click);
    content.addEventListener('change', change);
    return () => {
      content.removeEventListener('pointerdown', press);
      content.removeEventListener('pointermove', cursor);
      content.removeEventListener('pointerup', release);
      content.removeEventListener('pointercancel', release);
      content.removeEventListener('click', click);
      content.removeEventListener('change', change);
      body.current = null;
    };
  }, []);

  // The trusted assignment: `markup` is a COAST_RENDERERS result (see the header).
  useLayoutEffect(() => {
    const content = body.current;
    if (content && shown.current !== markup) {
      content.innerHTML = markup;
      shown.current = markup;
    }
  }, [markup]);

  return <div ref={host} class={props.class ? `app-coast-markup ${props.class}` : 'app-coast-markup'} data-coast-theme="tokens" data-renderer={props.renderer} />;
}
