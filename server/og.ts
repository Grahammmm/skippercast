import {regionById} from './config.ts';
import ports from '../catalog/home-ports.json' with {type: 'json'};

/** Chat previews name reviewed places, never visitor text or transient conditions. */
export function ogFor(search: URLSearchParams): {title: string; description: string} | null {
  const region = regionById(search.get('region'));
  if (!region?.name) return null;
  const port = search.getAll('port').length === 1
    ? ports.ports.find(p => p.id === search.get('port') && p.region === region.id) : undefined;
  return {
    title: `${port ? `${port.name}, ` : ''}${region.name} fishing conditions · SkipperCast`,
    description: `Wind, swell, tide and water temperature for ${region.name} on one map.`,
  };
}
