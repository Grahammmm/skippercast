import unittest

from scripts.check_nbs_modeling_scheme import latest_key


class NbsSchemeCheckTest(unittest.TestCase):
    def test_selects_latest_complete_official_scheme(self):
        xml = b'''<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
<IsTruncated>false</IsTruncated>
<Contents><Key>Test-and-Evaluation/Modeling/_Modeling_Tile_Scheme/Modeling_Tile_Scheme_20260922_120000.gpkg</Key></Contents>
<Contents><Key>Test-and-Evaluation/Modeling/_Modeling_Tile_Scheme/Modeling_Tile_Scheme_20260923_175019.gpkg</Key></Contents>
</ListBucketResult>'''
        self.assertTrue(latest_key(xml).endswith("20260923_175019.gpkg"))

    def test_rejects_truncated_list(self):
        xml = b'''<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
<IsTruncated>true</IsTruncated>
<Contents><Key>Test-and-Evaluation/Modeling/_Modeling_Tile_Scheme/Modeling_Tile_Scheme_20260923_175019.gpkg</Key></Contents>
</ListBucketResult>'''
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            latest_key(xml)


if __name__ == "__main__":
    unittest.main()
