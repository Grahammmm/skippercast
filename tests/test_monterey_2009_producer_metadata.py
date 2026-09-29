import unittest

from research.scripts.audit_monterey_2009_producer_metadata import evaluate


class ProducerMetadataTest(unittest.TestCase):
    def test_wrong_source_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            evaluate(b"Central Monterey Bay 2009")


if __name__ == "__main__":
    unittest.main()
