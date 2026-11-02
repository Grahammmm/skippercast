"""RF0720-7: a +1 phone must be a possible NANP number, else ``phone_e164`` is None.

Synthetic numbers only (555-01xx style); no real operator phone appears here.
"""
import unittest

from skippercast.fleet.normalize import NANP, phone_e164


class PhoneNanpTest(unittest.TestCase):
    def check(self, cases, **kwargs):
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(phone_e164(raw, **kwargs), expected)

    def test_area_code_starting_0_or_1_is_none(self):
        self.check([("012-345-6789", None), ("112-345-6789", None), ("(012) 555-0101", None),
                    ("1-112-555-0101", None), ("+1 012 555 0101", None), ("+1 112 555 0101", None)])

    def test_exchange_starting_0_or_1_is_none(self):
        self.check([("805-055-0101", None), ("805-155-0101", None), ("+1 805 055 0101", None),
                    ("1-805-155-0101 ext. 4", None)])

    def test_exchange_starting_2_to_9_is_kept(self):
        self.check([("805-255-0101", "+18052550101"), ("+1 805 955 0101", "+18059550101"),
                    ("205-555-0101", "+12055550101")])

    def test_plus_one_with_wrong_digit_count_is_none(self):
        self.check([("+1 805 555 0101 22", None), ("+1 805 555 01", None), ("+1 805 555 010", None),
                    ("+1 805 555 01011", None), ("+1", None), ("+11 805 555 0101", None)])

    def test_extensions_unchanged(self):
        self.check([("1-805-555-0102 ext. 4", "+18055550102"), ("(805) 555-0101 x12", "+18055550101"),
                    ("(805) 555-0101 extension 9", "+18055550101"), ("(805) 555-0101", "+18055550101")])

    def test_other_country_codes_unchanged(self):
        self.check([("+44 20 7946 0103", "+442079460103"), ("+52 55 1234 5678", "+525512345678"),
                    ("+44 012 345 6789", "+440123456789")])

    def test_ten_digits_with_other_country_untouched_by_nanp_rule(self):
        self.assertEqual(phone_e164("8055550101", country="44"), "+448055550101")
        self.assertEqual(phone_e164("0125550101", country="44"), "+440125550101")

    def test_country_one_eleven_digits_still_checked(self):
        self.check([("18055550101", "+18055550101"), ("10125550101", None), ("18051550101", None)])

    def test_non_strings_and_short_numbers_are_none(self):
        for raw in (None, 8055550101, 18055550101.0, ["805-555-0101"], "555-0101", ""):
            with self.subTest(raw=raw):
                self.assertIsNone(phone_e164(raw))

    def test_nanp_pattern_is_full_match_only(self):
        self.assertTrue(NANP.fullmatch("+18055550101"))
        self.assertIsNone(NANP.fullmatch("+180555501012"))
        self.assertIsNone(NANP.fullmatch("+1805555010"))


if __name__ == "__main__":
    unittest.main()
