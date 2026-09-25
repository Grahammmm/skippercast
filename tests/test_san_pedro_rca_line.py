import csv
from hashlib import sha256
import io
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import audit_san_pedro_rca_line as rca


def archive_with_local_line():
    output = io.BytesIO()
    with ZipFile(output, 'w') as zipfile:
        text = io.StringIO()
        writer = csv.writer(text)
        writer.writerow(['id_area', 'area_name', 'lat_dd', 'lon_dd'])
        for index in range(1, 202):
            writer.writerow([index, '50-fm (91-m) Contour - Coastwide', 33.65,
                             -120 + index * .01])
        zipfile.writestr(rca.CSV_NAME, text.getvalue())
    return output.getvalue()


def context_at(latitude):
    return {'features': [{'properties': {'id': 'one'},
        'geometry': {'type': 'Polygon', 'coordinates': [[[-118.25, latitude],
            [-118.249, latitude], [-118.249, latitude + .001],
            [-118.25, latitude + .001], [-118.25, latitude]]]}}]}


class RcaLineTest(unittest.TestCase):
    def test_archive_revision_is_held(self):
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            rca.audit(b'unreviewed', context_at(33.68))

    def test_shoreward_and_seaward_classification(self):
        raw = archive_with_local_line()
        with patch.object(rca, 'REVIEWED_ARCHIVE_SHA256', sha256(raw).hexdigest()):
            self.assertEqual(rca.audit(raw, context_at(33.68))['shoreward_count'], 1)
            self.assertEqual(rca.audit(raw, context_at(33.62))['seaward_count'], 1)
            self.assertFalse(rca.audit(raw, context_at(33.68))['outlines'][0]['fishing_target'])

    def test_near_boundary_requires_review(self):
        raw = archive_with_local_line()
        with patch.object(rca, 'REVIEWED_ARCHIVE_SHA256', sha256(raw).hexdigest()):
            self.assertEqual(rca.audit(raw, context_at(33.6501))['boundary_review_count'], 1)


if __name__ == '__main__':
    unittest.main()
