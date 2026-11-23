import {region} from './state.ts';
import {regionPorts, type RegionPorts} from './ports.ts';
import {currentRegionInfo, type RegionInfo} from './app/region-info.ts';

/** The loaded package's own recognized status decides for its region (preview says Preview, active never does,
 * whatever the directory says); with no same-region package status, a matching ready preview port still wins. */
export function isPreviewRegion(id: string | null, ports: RegionPorts | null, info: RegionInfo | null = null): boolean {
  if (!id) return false;
  if (info?.id === id && info.status) return info.status === 'preview';
  return ports?.region === id && ports.state === 'ready'
    && ports.list.some(port => port.region === id && port.status === 'preview');
}

/** Never reuse another region's status while its replacement is loading or unavailable. */
export const currentRegionPreview = (): boolean => isPreviewRegion(region.value, regionPorts.value, currentRegionInfo());
