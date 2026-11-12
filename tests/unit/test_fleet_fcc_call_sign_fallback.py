"""RF2150-6: a blank (whitespace-only) SH call sign falls back to the licence's HD call sign.

Synthetic in-memory ZIPs only; no network.
"""
import io
import unittest
import zipfile

from skippercast.fleet.adapters.fcc_uls import parse_ship_zip

NOW = "2026-10-05T09:47:00Z"
USI = "9000001"


def _row(kind, call_sign, width, extra):
    fields = [""] * width
    fields[0], fields[1], fields[4] = kind, USI, call_sign
    for index, value in extra.items():
        fields[index] = value
    return "|".join(fields) + "\r\n"


def build(sh_call, hd_call="ZZZ9001", with_hd=True):
    en = _row("EN", "", 24, {5: "L", 7: "EXAMPLE SPORTFISHING LLC", 17: "CA", 23: "L"})
    hd = _row("HD", hd_call, 10, {5: "A", 6: "SA", 7: "01/15/2020", 8: "01/15/2030"}) if with_hd else ""
    sh = _row("SH", sh_call, 22, {5: "R", 8: "CHR", 9: "SEA EXAMPLE", 10: "1234567", 21: "999000001"})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("EN.dat", en)
        archive.writestr("HD.dat", hd)
        archive.writestr("SH.dat", sh)
    return buffer.getvalue()


def run(data):
    stats = {}
    out = list(parse_ship_zip(data, "CA", source_id="fcc-uls", rights="public-domain", retrieved_at=NOW, stats=stats))
    return out, stats


def seen(candidate):
    calls = [f.value for f in candidate.facts if f.field == "call_sign"]
    licence = next(f.value for f in candidate.facts if f.field == "fcc_licence")
    return candidate.keys.get("call_sign"), calls, licence.get("call_sign")


class CallSignFallbackTests(unittest.TestCase):
    def test_blank_sh_uses_header_everywhere(self):
        control, control_stats = run(build(""))
        self.assertEqual(seen(control[0]), ("ZZZ9001", ["ZZZ9001"], "ZZZ9001"))
        for blank in ("   ", "\t ", " \t "):
            with self.subTest(blank=blank):
                got, stats = run(build(blank))
                self.assertEqual(got, control)
                self.assertEqual(stats, control_stats)

    def test_nonblank_sh_wins(self):
        got, _ = run(build(" zzz9002 ", hd_call="ZZZ9001"))
        self.assertEqual(seen(got[0]), ("ZZZ9002", ["ZZZ9002"], "ZZZ9002"))

    def test_header_is_normalized(self):
        for sh in ("", "  "):
            got, _ = run(build(sh, hd_call=" zzz9001 "))
            self.assertEqual(seen(got[0]), ("ZZZ9001", ["ZZZ9001"], "ZZZ9001"))

    def test_missing_header_or_both_blank_invents_nothing(self):
        got, _ = run(build("zzz9002", with_hd=False))
        self.assertEqual(seen(got[0]), ("ZZZ9002", ["ZZZ9002"], "ZZZ9002"))
        for data in (build("   ", with_hd=False), build("  ", hd_call="   ")):
            got, _ = run(data)
            self.assertEqual(len(got), 1)
            self.assertEqual(seen(got[0]), (None, [], None))

    def test_invalid_nonblank_sh_does_not_fall_back(self):
        got, _ = run(build("!!", hd_call="ZZZ9001"))
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0].keys.get("call_sign"))
        self.assertEqual(got[0].keys.get("mmsi"), "999000001")


if __name__ == "__main__":
    unittest.main()
