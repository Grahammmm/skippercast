"""A coastal browse directory, separate from qualified regional data packages."""
from .contracts import REPO, read_json, atomic_json, public_url, load_catalogs, bbox


def compile_coasts(root=REPO):
    directory = read_json(root / 'catalog/coasts.json')
    needs,sources=load_catalogs(root)
    for need,ident in directory['source_bindings'].items():
        provider=sources.get(ident,{})
        if need not in needs or need not in provider.get('needs',[]) or provider.get('review_status')!='approved':
            raise ValueError('Coastal source binding must be reviewed for its data need')
    targets = {**read_json(root / 'catalog/targets.json')['targets'], **directory['extra_targets']}
    species = {s['id']: s for s in read_json(root / 'catalog/species.json')['species']}
    regions = directory['regions']
    if [r['id'] for r in regions] != ['northern', 'mendocino', 'san-francisco', 'central', 'southern']:
        raise ValueError('Unexpected coastal directory')
    for i, region in enumerate(regions):
        bbox(region['bounds'])
        public_url(region['rules_url'])
        if region.get('groundfish_table_url'):
            public_url(region['groundfish_table_url'])
            if not region['groundfish_table_url'].startswith('https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID='):
                raise ValueError('Groundfish table must link to the reviewed CDFW document service')
        if i and regions[i-1]['latitude'][0] != region['latitude'][1]:
            raise ValueError('Coastal latitude boundaries must meet exactly')
        if len(set(region['targets'])) != len(region['targets']):
            raise ValueError('Duplicate coastal target')
        for ident in region['targets'] + region['watch']:
            if ident not in targets:
                raise ValueError('Unknown biological target')
        for ident in region['packages']:
            if not (root / f'regions/{ident}/region.json').is_file():
                raise ValueError('Unknown mapped package')
        options = []
        for ident in dict.fromkeys(region['targets'] + region['watch']):
            target = {'id': ident, **targets[ident]}
            target['name'] = region.get('target_labels', {}).get(ident, target['name'])
            records = [species[s] for s in target['source_species'] if s in species]
            target['note'] = target.get('note') or ' '.join(s['claims'][0]['claim'] for s in records)
            target['sources'] = list(dict.fromkeys([target['source_url']] if target.get('source_url') else [c['source_url'] for s in records for c in s['claims']]))
            options.append(target)
        region['target_options'] = [t for t in options if t['id'] in region['targets']]
        region['watch_options'] = [t for t in options if t['id'] in region['watch']]
    directory['target_names'] = {k: v['name'] for k, v in targets.items()}
    directory.pop('extra_targets')
    atomic_json(root / 'dist/data/coasts.json', directory)
    return directory
