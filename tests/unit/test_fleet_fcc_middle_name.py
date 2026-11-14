"""RF0600-9: an FCC EN licensee with a populated middle-initial field (position 9) is not emitted as an operator.

In-memory Latin-1 zips of invented values only; no network. The vessel candidate, keys, port hint and every
non-operator fact stay; only the uncertain licensee entity is withheld.
"""
import io
import unittest
import zipfile

from skippercast.fleet.adapters.fcc_uls import parse_ship_zip

NOW = "2026-10-05T09:47:00Z"
PORTS = {"MORROBAY": "morro-bay"}


def en(usi, name="SYNTHETIC ENTITY LLC", first="", middle="", last="", kind="L", applicant="C", city="Morro Bay"):
    f = [""] * 30
    f[0], f[1], f[5], f[7], f[8], f[9], f[10] = "EN", usi, kind, name, first, middle, last
    f[16], f[17], f[23] = city, "CA", applicant
    return "|".join(f)


def hd(usi, call):
    f = [""] * 12
    f[0], f[1], f[4], f[5], f[6], f[7], f[8] = "HD", usi, call, "A", "SA", "01/02/2020", "01/02/2030"
    return "|".join(f)


def sh(usi, call, vessel):
    f = [""] * 24
    f[0], f[1], f[4], f[8], f[9] = "SH", usi, call, "PA", vessel
    return "|".join(f)


def build(*en_rows, usis=("9001",)):
    members = {"EN.dat": "\r\n".join(en_rows) + "\r\n",
               "HD.dat": "\r\n".join(hd(u, f"ZZZ{u}") for u in usis) + "\r\n",
               "SH.dat": "\r\n".join(sh(u, f"ZZZ{u}", f"SYNTHETIC VESSEL {u}") for u in usis) + "\r\n"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, body.encode("latin-1"))
    return buffer.getvalue()


def run(data):
    stats = {}
    out = list(parse_ship_zip(data, "CA", source_id="fcc-uls", rights="public-domain", retrieved_at=NOW,
                              ports=PORTS, stats=stats))
    return out, stats


def operators(candidate):
    return [f.value for f in candidate.facts if f.field == "operator"]


def without_operator(candidate):
    return [f for f in candidate.facts if f.field != "operator"]


class MiddleNameScreenTests(unittest.TestCase):
    def control(self):
        out, stats = run(build(en("9001")))
        self.assertEqual(operators(out[0]), ["SYNTHETIC ENTITY LLC"])
        return out[0], stats

    def test_middle_initial_withholds_entity_only(self):
        base, base_stats = self.control()
        out, stats = run(build(en("9001", middle="X")))
        self.assertEqual(len(out), 1)
        self.assertEqual(operators(out[0]), [])
        self.assertEqual(out[0].name, base.name)
        self.assertEqual(out[0].keys, base.keys)
        self.assertEqual(out[0].port_hint, "morro-bay")
        self.assertEqual(out[0].port_hint, base.port_hint)
        self.assertEqual(out[0].facts, tuple(without_operator(base)))
        self.assertEqual(stats, base_stats)

    def test_middle_name_and_padded_initial_are_personal_components(self):
        base, _ = self.control()
        for middle in ("EXAMPLE", " X "):
            with self.subTest(middle=middle):
                out, _ = run(build(en("9001", middle=middle)))
                self.assertEqual(operators(out[0]), [])
                self.assertEqual(out[0].facts, tuple(without_operator(base)))
                self.assertNotIn(middle.strip(), repr(out[0]))

    def test_empty_and_whitespace_middle_preserve_entities(self):
        base, base_stats = self.control()
        for middle in ("", "   ", "\t "):
            with self.subTest(middle=repr(middle)):
                out, stats = run(build(en("9001", middle=middle)))
                self.assertEqual(out, [base])
                self.assertEqual(stats, base_stats)

    def test_existing_refusals_remain_regardless_of_middle(self):
        for kwargs in ({"first": "SYNTH"}, {"last": "SYNTH"}, {"applicant": "I"}, {"name": "SYNTHETIC ENTITY"},
                       {"name": "SYNTHETIC ENTITY LLC DBA OTHER"}):
            for middle in ("", "X"):
                with self.subTest(kwargs=kwargs, middle=middle):
                    out, _ = run(build(en("9001", middle=middle, **kwargs)))
                    self.assertEqual(len(out), 1)
                    self.assertEqual(operators(out[0]), [])

    def test_screen_is_licensee_local(self):
        out, stats = run(build(en("9001", middle="X"), en("9002", name="OTHER SYNTHETIC INC"),
                               en("9002", name="CONTACT PERSON LLC", kind="CL", middle="Q"),
                               usis=("9001", "9002")))
        by_name = {c.name: c for c in out}
        self.assertEqual(operators(by_name["SYNTHETIC VESSEL 9001"]), [])
        self.assertEqual(operators(by_name["SYNTHETIC VESSEL 9002"]), ["OTHER SYNTHETIC INC"])
        self.assertEqual((stats["licences"], stats["candidates"], stats["unnamed"]), (2, 2, 0))
        self.assertNotIn("'Q'", repr(out))


if __name__ == "__main__":
    unittest.main()
