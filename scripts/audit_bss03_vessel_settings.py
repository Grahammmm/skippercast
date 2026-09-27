"""Audit the small original Block 03 CARIS vessel-config archive.

These are TPU *input settings*, not a decoded sounding or gridded depth error.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


URL = ('https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/'
       'BSS_Block03/multibeam/data/version2/ancillary/BSS_vesselconfig_caris.tar.gz')
MAX_BYTES = 30_000
EXPECTED_FILES = ('22HaroldHeath.hvf', '22HaroldHeath_PPK.hvf',
                  '42HaroldHeath.hvf', '42HaroldHeath_PPK.hvf',
                  '45HaroldHeath.hvf', '45HaroldHeath_PPK.hvf',
                  '7111HaroldHeath.hvf', '7111HaroldHeath_PPK.hvf')


def fetch():
    with urlopen(Request(URL, headers={
            'User-Agent': 'SkipperCast original-survey-source-review/1.0'}), timeout=30) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError('Official vessel-config source unavailable or redirected')
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Vessel-config archive exceeded download bound')
    return data


def inspect(data):
    rows = []
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = {Path(m.name).name: m for m in archive if m.isfile()}
        if not set(EXPECTED_FILES).issubset(members):
            raise ValueError('Expected original Harold Heath vessel configurations missing')
        for name in EXPECTED_FILES:
            member = members[name]
            if member.size > 20_000:
                raise ValueError('Unexpected vessel-configuration member size')
            raw = archive.extractfile(member).read()
            root = ET.fromstring(raw)
            if root.tag != 'HIPSVesselConfig':
                raise ValueError('Unexpected CARIS vessel-config XML')
            standard = root.find('.//StandardDeviation')
            if standard is None:
                raise ValueError('Vessel configuration lacks TPU input settings')
            motion, position, timing = (standard.find(tag) for tag in ('Motion', 'Position', 'Timing'))
            if any(node is None for node in (motion, position, timing)):
                raise ValueError('Incomplete vessel-config standard deviation settings')
            rows.append({
                'member': member.name,
                'member_sha256': hashlib.sha256(raw).hexdigest(),
                'navigation_input': float(position.attrib['Navigation']),
                'heave_input': float(motion.attrib['Heave']),
                'heave_percent_amplitude_input': float(motion.attrib['HeavePercAmplitude']),
                'navigation_timing_input': float(timing.attrib['Navigation']),
            })
    if (len(rows) != 8 or any(row['navigation_input'] != 0.1 or row['heave_input'] != 0.05
                              or row['heave_percent_amplitude_input'] != 5.0
                              or row['navigation_timing_input'] != 0.001 for row in rows)):
        raise ValueError('Original TPU input values changed')
    return {
        'schema_version': 1,
        'scope': 'bss03-original-vessel-tpu-inputs',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'source_url': URL,
        'source_bytes': len(data),
        'source_sha256': hashlib.sha256(data).hexdigest(),
        'vessel_configurations': rows,
        'line_to_configuration_assignment_verified': False,
        'survey_or_cell_total_propagated_uncertainty_verified': False,
        'released_grid_upper_error_verified': False,
        'depth_qualified': False,
        'fishing_target': False,
        'exportable': False,
        'interpretation': ('CARIS vessel files specify nominal input standard deviations. '
                           'They do not provide the resulting sounding TPU, grid CUBE/BASE '
                           'uncertainty, tide/vertical datum error, or final raster error bound.'),
    }


def stable(report):
    return {key: value for key, value in report.items() if key != 'checked_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=Path('dist/data/bss03-original-vessel-tpu-inputs.json'))
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    report = inspect(fetch())
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit('Original CARIS vessel TPU inputs changed; review before publishing')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('8 vessel configurations audited; depth qualification remains blocked')


if __name__ == '__main__':
    main()
