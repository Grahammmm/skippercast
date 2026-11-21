export const EDGE_LAYERS = ['sst-fronts', 'chl-edges', 'eddies'] as const;
export type EdgeLayer = typeof EDGE_LAYERS[number];

type EdgesGroup = {
  state: 'none' | 'off' | 'on' | 'mixed';
  members: {id: EdgeLayer; on: boolean; available: boolean}[];
};

export function edgesGroup(on: ReadonlySet<string>, available: ReadonlySet<string>): EdgesGroup {
  const members = EDGE_LAYERS.map(id => {
    const isAvailable = available.has(id);
    return {id, on: isAvailable && on.has(id), available: isAvailable};
  });
  const availableCount = members.filter(member => member.available).length;
  const onCount = members.filter(member => member.on).length;
  const state = availableCount === 0 ? 'none'
    : onCount === 0 ? 'off'
    : onCount === availableCount ? 'on'
    : 'mixed';
  return {state, members};
}

export function toggleEdgesGroup(on: ReadonlySet<string>, available: ReadonlySet<string>): Set<string> {
  const next = new Set(on);
  const {state, members} = edgesGroup(on, available);
  if (state === 'on') {
    for (const id of EDGE_LAYERS) next.delete(id);
  } else if (state === 'off' || state === 'mixed') {
    for (const member of members) {
      if (member.available) next.add(member.id);
    }
  }
  return next;
}

export function toggleEdge(on: ReadonlySet<string>, available: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(on);
  if (!EDGE_LAYERS.some(layer => layer === id) || !available.has(id)) return next;
  if (on.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
