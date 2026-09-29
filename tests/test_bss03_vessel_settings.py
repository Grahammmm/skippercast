import io
import tarfile
import unittest

from research.scripts import audit_bss03_vessel_settings as audit


class Bss03VesselSettingsTests(unittest.TestCase):
    def test_missing_original_config_fails_closed(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            raw = b'<HIPSVesselConfig />'
            member = tarfile.TarInfo('VesselConfig/45HaroldHeath.hvf')
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
        with self.assertRaisesRegex(ValueError, 'configurations missing'):
            audit.inspect(stream.getvalue())

    def test_vessel_inputs_cannot_be_promoted_to_product_uncertainty(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name in audit.EXPECTED_FILES:
                raw = (b'<HIPSVesselConfig><StandardDeviation>'
                       b'<Motion Heave="0.05" HeavePercAmplitude="5" />'
                       b'<Position Navigation="0.1" />'
                       b'<Timing Navigation="0.001" />'
                       b'</StandardDeviation></HIPSVesselConfig>')
                member = tarfile.TarInfo('VesselConfig/' + name)
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        receipt = audit.inspect(stream.getvalue())
        self.assertEqual(len(receipt['vessel_configurations']), 8)
        self.assertFalse(receipt['line_to_configuration_assignment_verified'])
        self.assertFalse(receipt['survey_or_cell_total_propagated_uncertainty_verified'])
        self.assertFalse(receipt['released_grid_upper_error_verified'])
        self.assertFalse(receipt['fishing_target'])


if __name__ == '__main__':
    unittest.main()
