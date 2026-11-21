/**
 * A layer module may export `themePaint(palette): readonly {layer: string;
 * property: string; value: unknown}[]` and/or `themePatterns(palette): readonly
 * {id: string; image: ImageData; pixelRatio: number}[]`. These contracts are
 * structural: providers do not have to import anything from this module.
 *
 * `restyle` uses only the `Restylable` paint and image methods. It applies every
 * edit for an existing layer and reports missing layer IDs. It replaces an
 * existing pattern in place, or adds it once if absent. A given image ID keeps
 * the same dimensions and pixel ratio across themes so it can be updated in
 * place. Restyling never changes the camera, sources or data. New layers should
 * be built with the current palette.
 */
import type {Palette} from './palette.ts';
import {basemapStyle} from './style.ts';

type PaintEdit = {layer: string; property: string; value: unknown};
type Pattern = {id: string; image: ImageData; pixelRatio: number};

export interface Provider {
  themePaint?(palette: Palette): readonly PaintEdit[];
  themePatterns?(palette: Palette): readonly Pattern[];
}

export interface Restylable {
  hasLayer(id: string): boolean;
  setPaintProperty(layer: string, property: string, value: unknown): void;
  hasImage(id: string): boolean;
  updateImage(id: string, image: ImageData): void;
  addImage(id: string, image: ImageData, options: {pixelRatio: number}): void;
}

/** `applied` counts paint edits, and `skipped` lists each missing layer once. */
export function restyle(target: Restylable, palette: Palette, providers: readonly Provider[]): {applied: number; skipped: string[]} {
  // Register/refresh images before painting anything that may reference them.
  for (const provider of providers) {
    for (const {id, image, pixelRatio} of provider.themePatterns?.(palette) ?? []) {
      if (target.hasImage(id)) target.updateImage(id, image);
      else target.addImage(id, image, {pixelRatio});
    }
  }
  let applied = 0;
  const skipped = new Set<string>();
  for (const provider of providers) {
    for (const {layer, property, value} of provider.themePaint?.(palette) ?? []) {
      if (!target.hasLayer(layer)) {
        skipped.add(layer);
        continue;
      }
      target.setPaintProperty(layer, property, value);
      applied++;
    }
  }
  return {applied, skipped: [...skipped]};
}

/**
 * Project the `paint` entries of built layer specs into edits, so a layer
 * module's `themePaint` can reuse its own pure builder rather than restate IDs
 * and values. `keep` picks properties by name; the default keeps every one
 * (MapLibre skips a `setPaintProperty` whose value is unchanged). Layout,
 * sources and layers without `paint` contribute nothing.
 */
export function paintEdits(
  layers: readonly {readonly id: string; readonly paint?: object}[],
  keep: (property: string) => boolean = () => true,
): readonly PaintEdit[] {
  return layers.flatMap(({id: layer, paint}) => Object.entries(paint ?? {})
    .filter(([property]) => keep(property))
    .map(([property, value]) => ({layer, property, value})));
}

/** Project just the Chart basemap's theme-dependent paints, not its sources or layout. */
export function basemapThemePaint(palette: Palette): readonly PaintEdit[] {
  // The style builder is pure. Use its layers so the initial draw and restyle
  // share the very same layer IDs, token roles and numeric controls.
  const {layers} = basemapStyle(palette, {archive: '', assets: ''});
  return paintEdits(layers, property => property.endsWith('-color') || property === 'line-opacity' || property === 'text-opacity');
}

/**
 * Subscribe to theme changes. Apply immediately when idle; while an apply is
 * in flight, retain only the latest notification and apply it after settling.
 * The notification that starts a drain returns its completion (and first apply
 * error, if any) to the subscriber. Disposing drops queued and future work,
 * but cannot cancel an apply that has already started.
 */
export function createThemeWatcher<Theme>(
  subscribe: (notify: (theme: Theme) => Promise<void>) => () => void,
  apply: (theme: Theme) => void | Promise<void>,
): () => void {
  let stopped = false;
  let applying = false;
  let pending: {theme: Theme} | undefined;
  const unsubscribe = subscribe(async theme => {
    if (stopped) return;
    pending = {theme};
    if (applying) return;
    applying = true;
    let failure: {error: unknown} | undefined;
    while (pending) {
      const next = pending.theme;
      pending = undefined;
      try {
        const result = apply(next);
        if (result !== undefined) await result;
      } catch (error) {
        failure ??= {error};
      }
    }
    applying = false;
    if (failure) throw failure.error;
  });
  return () => {
    if (stopped) return;
    stopped = true;
    pending = undefined;
    unsubscribe();
  };
}
