export const DATA_ALERT_LAYERS = ['sst-analysis', 'chlorophyll-observation'] as const;
export type DataAlertLayer = typeof DATA_ALERT_LAYERS[number];

export function readDataAlerts(data: unknown): Set<DataAlertLayer> | null {
  if (typeof data !== 'object' || data === null) return null;
  try {
    if (Array.isArray(data)) return null;
    const prototype = Object.getPrototypeOf(data);
    if (prototype !== Object.prototype && prototype !== null) return null;
    if (!Object.hasOwn(data, 'layers')) return null;
    const {layers} = data as {layers: unknown};
    if (!Array.isArray(layers)) return null;

    const on = new Set<DataAlertLayer>();
    for (let i = 0; i < layers.length; i++) {
      const layer: unknown = layers[i];
      if (typeof layer !== 'string') return null;
      const known = DATA_ALERT_LAYERS.find(id => id === layer);
      if (known !== undefined) on.add(known);
    }
    return on;
  } catch {
    return null;
  }
}

export function toggleDataAlert(on: ReadonlySet<string>, layer: string): Set<DataAlertLayer> {
  return new Set(DATA_ALERT_LAYERS.filter(known => known === layer ? !on.has(known) : on.has(known)));
}

export function dataAlertsChanged(saved: ReadonlySet<string>, current: ReadonlySet<string>): boolean {
  return DATA_ALERT_LAYERS.some(layer => saved.has(layer) !== current.has(layer));
}

export function dataAlertsBody(current: ReadonlySet<string>): {layers: DataAlertLayer[]} {
  return {layers: DATA_ALERT_LAYERS.filter(layer => current.has(layer))};
}
