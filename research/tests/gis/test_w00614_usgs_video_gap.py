import io
import zipfile
import unittest

import shapefile

from research.scripts.audit_w00614_usgs_video_gap import inspect_zip


def point_archive(points):
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POINT)
    writer.field('sample', 'N')
    for index, (lon, lat) in enumerate(points):
        writer.point(lon, lat)
        writer.record(index)
    writer.close()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for suffix, data in (('shp', shp), ('shx', shx), ('dbf', dbf)):
            archive.writestr('original.' + suffix, data.getvalue())
        archive.writestr('original.prj', 'GEOGCS["GCS_WGS_1984"]')
    return stream.getvalue()


class VideoGapTests(unittest.TestCase):
    def test_near_point_requires_exact_cell_review(self):
        bounds = [-122.4847, 37.1138, -122.4431, 37.1629]
        result = inspect_zip(point_archive([(-122.46, 37.13),
                                            (-122.42342, 37.18193)]), bounds)
        self.assertEqual(result['points_in_qualified_cell_center_envelope'], 1)
        self.assertEqual(result['points_within_100m_of_envelope'], 1)
        self.assertEqual(result['observation_points'], 2)

    def test_distant_point_cannot_support_cell(self):
        bounds = [-122.4847, 37.1138, -122.4431, 37.1629]
        result = inspect_zip(point_archive([(-122.42342, 37.18193)]), bounds)
        self.assertEqual(result['points_within_100m_of_envelope'], 0)
        self.assertGreater(result['approx_min_distance_to_envelope_m'], 2000)


if __name__ == '__main__':
    unittest.main()
