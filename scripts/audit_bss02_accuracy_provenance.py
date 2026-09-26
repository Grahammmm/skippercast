"""Check whether Block 02's published accuracy points independently observe seabed."""
import argparse
import json
from pathlib import Path
import tarfile
from xml.etree import ElementTree

from scripts.audit_csumb_bss_native import ROOT, acquire


METADATA = 'BSS_Block02/Habitat/BSS_Block02_accuracy_assessment.shp.xml'


def inspect(spec, cache):
    if spec['survey_id'] != 'BSS_Block02':
        raise ValueError('Only the reviewed Block 02 assessment is supported')
    archive = acquire(spec, cache, False)
    with tarfile.open(archive, 'r:gz') as bundle:
        member = bundle.getmember(METADATA)
        if member.size > 500_000:
            raise ValueError('Unexpected accuracy metadata size')
        root = ElementTree.fromstring(bundle.extractfile(member).read())
    descriptions = [' '.join(''.join(node.itertext()).split()) for node in root.iter()
                    if node.tag.rsplit('}', 1)[-1].lower() == 'procdesc']
    process = ' '.join(descriptions).lower()
    required = ('randomly located accuracy assessment points (n=100)',
                'visual interpretation of the bathymetric shaded-relief image',
                'rugosity-based substrate classification',
                'overall percent agreement was 100%')
    if not all(fragment in process for fragment in required):
        raise ValueError('Original accuracy method changed; review before use')
    return {
        'source_id': spec['id'], 'archive_url': spec['archive_url'],
        'archive_sha256': spec['archive_sha256'], 'metadata_member': METADATA,
        'assessment_points': 100, 'reported_agreement_percent': 100,
        'reference_method': 'visual interpretation of bathymetric shaded-relief image',
        'comparison_method': 'rugosity-based substrate classification of the same bathymetry',
        'independent_seabed_observation': False,
        'rank_effect': 'none',
        'reason': 'Both sides of the accuracy comparison derive from the same bathymetry; no video, grab sample, or independent rock observation is established by this assessment.',
        'publication_status': 'source-method-review-only',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'catalog/csumb-bss-native-sources.json')
    parser.add_argument('--cache', type=Path, default=ROOT / 'var/noaa-native-cache')
    parser.add_argument('--output', type=Path, default=ROOT / 'var/review/bss02-accuracy-provenance.json')
    args = parser.parse_args()
    spec = next(source for source in json.loads(args.manifest.read_text())['sources']
                if source['survey_id'] == 'BSS_Block02')
    receipt = inspect(spec, args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.partial')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps({'source_id': receipt['source_id'], 'independent_seabed_observation': False,
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
