// Snapshot public region labels for offline, private calendar exports.
import {readdir, readFile, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

export async function calendarRegions() {
  const ids = (await readdir('dist/regions', {withFileTypes: true})).filter(e => e.isDirectory()).map(e => e.name).sort();
  const regions = [];
  for (const id of ids) {
    let region;
    try { region = JSON.parse(await readFile(`dist/regions/${id}/region.json`, 'utf8')); }
    catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    regions.push({id: region.id, timezone: region.timezone, species: region.species,
      forecast_points: region.forecast_points.map(({id, name}) => ({id, name})),
      target_options: (region.target_options ?? []).map(({id, name}) => ({id, name}))});
  }
  return regions;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await writeFile('web/trip-calendar-regions.generated.json', JSON.stringify(await calendarRegions()) + '\n');
}
