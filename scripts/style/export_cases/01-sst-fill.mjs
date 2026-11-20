import {sampleDisplay, scalarGrid} from '../../../web/map/field.ts';
import {sstDataIsFresh} from '../../../web/map/sst.ts';
import {sstBandModel, sstBandPixels, sstRamp, SST_STYLE} from '../../../web/map/sst-bands.ts';

export async function render(input, {palette, readGrid, now}) {
  const {case: id, view, zoom, data_time_utc, source_grid: source, view_grid: display} = input;
  const metrics = {case: id, pick: SST_STYLE.pick, view, zoom, data_time_utc};
  // The reference fixture exposes one UTC timestamp and no retrieval timestamp.
  const iso = /(?:Z|[+-]\d{2}:\d{2})$/.test(data_time_utc) ? data_time_utc : `${data_time_utc}Z`;
  if (!sstDataIsFresh({analysedAt: iso, fetchedAt: iso}, new Date(now ?? iso))) {
    return {metrics: {...metrics, withheld: true}};
  }
  const [values, mask] = await Promise.all([readGrid(source.values), readGrid(display.mask)]);
  const celsius = scalarGrid(source.lon, source.lat, values);
  const samples = sampleDisplay({...display, mask}, (lon, lat) => celsius(lon, lat) * 1.8 + 32);
  const bands = sstBandModel(samples, zoom);
  if (!bands) throw new Error('SST case has no supported display samples');
  return {
    metrics: {...metrics, base_desaturation: bands.baseDesaturation, sst_lo_f: bands.low, sst_hi_f: bands.high,
      band_step_f: bands.step, n_bands: bands.count, opacity: bands.opacity, sst_mean_f: bands.mean},
    rgba: sstBandPixels(samples, bands, sstRamp(palette), bands.opacity),
  };
}
