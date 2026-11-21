type SpotFocus = {
  region: string;
  spotId: string;
  layer: 'water-temp' | 'chlorophyll' | 'sst-contrast';
};

export function readSpotFocus(search: string | URLSearchParams): SpotFocus | null {
  const params = typeof search === 'string' ? new URLSearchParams(search) : search;
  const regions = params.getAll('region');
  const spots = params.getAll('spot');
  const layers = params.getAll('layers');
  if (regions.length !== 1 || spots.length !== 1 || layers.length !== 1) return null;

  const [region = ''] = regions;
  const [spotId = ''] = spots;
  const [layer] = layers;
  if (!/^[a-z0-9-]{1,64}$/.test(region)) return null;
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(spotId)) return null;
  if (layer !== 'water-temp' && layer !== 'chlorophyll' && layer !== 'sst-contrast') return null;
  return {region, spotId, layer};
}
