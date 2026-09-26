import unittest

from scripts.audit_estero_release_inventory import build


class EsteroReleaseInventoryTest(unittest.TestCase):
    def test_only_listed_sources_do_not_qualify_depth(self):
        links = "".join(f'<a href="data/{name}">data</a>' for name in (
            "Amplitude_utm10_EsteroBay.zip", "WGS84_utm10_EsteroBay.zip",
            "NAD83_utm10_EsteroBay.zip", "StDev_utm10_EsteroBay.zip"))
        result = build({"data_tables.html": links.encode(),
                        "data_processing.html": b"Total Propagated Uncertainty and Swath Angle BASE"})
        self.assertFalse(result["listed_tpu_or_base_surface"])
        self.assertFalse(result["fishing_target"])
        self.assertEqual(result["qualified_waypoints"], 0)

    def test_new_zip_requires_review(self):
        links = "".join(f'<a href="data/{name}">data</a>' for name in (
            "Amplitude_utm10_EsteroBay.zip", "WGS84_utm10_EsteroBay.zip",
            "NAD83_utm10_EsteroBay.zip", "StDev_utm10_EsteroBay.zip",
            "TPU_utm10_EsteroBay.zip"))
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            build({"data_tables.html": links.encode(),
                   "data_processing.html": b"Total Propagated Uncertainty and Swath Angle BASE"})

    def test_dynamic_page_script_does_not_change_inventory(self):
        base = "".join(f'<a href="data/{name}">{name}</a>' for name in (
            "Amplitude_utm10_EsteroBay.zip", "WGS84_utm10_EsteroBay.zip",
            "NAD83_utm10_EsteroBay.zip", "StDev_utm10_EsteroBay.zip"))
        pages = {"data_tables.html": base.encode(),
                 "data_processing.html": b"Total Propagated Uncertainty and Swath Angle BASE"}
        first = build(pages)
        pages["data_tables.html"] += b"<script>changing request token 1</script>"
        pages["data_processing.html"] += b"<script>changing request token 2</script>"
        self.assertEqual(first, build(pages))

    def test_nonzip_download_link_changes_page_fingerprint(self):
        base = "".join(f'<a href="data/{name}">{name}</a>' for name in (
            "Amplitude_utm10_EsteroBay.zip", "WGS84_utm10_EsteroBay.zip",
            "NAD83_utm10_EsteroBay.zip", "StDev_utm10_EsteroBay.zip"))
        pages = {"data_tables.html": base.encode(),
                 "data_processing.html": b"Total Propagated Uncertainty and Swath Angle BASE"}
        first = build(pages)
        pages["data_tables.html"] += b'<a href="data/Estero_TPU.bag">data</a>'
        self.assertNotEqual(first["source_pages"]["data_tables.html"],
                            build(pages)["source_pages"]["data_tables.html"])


if __name__ == "__main__":
    unittest.main()
