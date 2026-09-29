import io
import tarfile
import unittest

from research.scripts.audit_bss03_caris_tpe_member import MEMBER, build


def archive(tpe=b"HDCS\0\x01"):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for name, data in ((MEMBER, tpe), ("following/header", b"next")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


class CarisTpeMemberTest(unittest.TestCase):
    def test_complete_member_requires_following_tar_header(self):
        data = archive()
        result = build(data, prefix_bytes=len(data), tpe_bytes=6)
        self.assertEqual(result["tpe_member_bytes"], 6)
        self.assertFalse(result["grid_cell_upper_uncertainty_verified"])

    def test_binary_without_hdcs_identity_fails(self):
        data = archive(b"wrong!")
        with self.assertRaisesRegex(ValueError, "member or following"):
            build(data, prefix_bytes=len(data), tpe_bytes=6)


if __name__ == "__main__":
    unittest.main()
