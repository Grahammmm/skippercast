import {region} from './state.ts';
import {regionPorts, type RegionPorts} from './ports.ts';

/** Coverage comes from home-ports: any matching preview port wins a disagreement. */
export function isPreviewRegion(id: string | null, ports: RegionPorts | null): boolean {
  return !!id && ports?.region === id && ports.state === 'ready'
    && ports.list.some(port => port.region === id && port.status === 'preview');
}

/** Never reuse another region's status while its replacement is loading or unavailable. */
export const currentRegionPreview = (): boolean => isPreviewRegion(region.value, regionPorts.value);
