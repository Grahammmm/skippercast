import io
import tarfile
import unittest

from scripts import audit_bss03_vessel_settings as audit


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

    def test_current_original_archive_is_input_evidence_only(self):
        receipt = audit.inspect(audit.fetch())
        self.assertEqual(len(receipt['vessel_configurations']), 8)
        self.assertFalse(receipt['line_to_configuration_assignment_verified'])
        self.assertFalse(receipt['survey_or_cell_total_propagated_uncertainty_verified'])
        self.assertFalse(receipt['released_grid_upper_error_verified'])
        self.assertFalse(receipt['fishing_target'])


if __name__ == '__main__':
    unittest.main()
