"""phone_e164 refuses non-ASCII decimal digits instead of keeping or deleting them."""

import re
import unittest

from skippercast.fleet.normalize import phone_e164


class PhoneAsciiDigitsTest(unittest.TestCase):
    def test_unicode_decimal_digits_are_not_e164(self):
        cases = [
            "+1 8\u06605 555 0101",  # Arabic-Indic zero
            "+1 805 555 010\uff11",  # fullwidth one
            "805 555 010\u0967",  # Devanagari one, NANP without plus
            "+44 20 7946 095\u0669",  # international
            "+\u0661\u0668\u0660\u0665\u0665\u0665\u0665\u0660\u0661\u0660\u0661",  # all Arabic-Indic
            "(805) 555-0101 \uff58\u0661\u0662",  # unicode digits only in the extension
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(phone_e164(text))

    def test_unicode_digits_are_not_silently_deleted(self):
        # Dropping the Unicode digit would leave a plausible, different 10-digit number.
        self.assertIsNone(phone_e164("805 555 01\u0660 1 2"))
        self.assertIsNone(phone_e164("805 555 010\uff10 1"))
        self.assertEqual(phone_e164("805 555 0101"), "+18055550101")

    def test_ascii_controls_and_extensions_unchanged(self):
        self.assertEqual(phone_e164("(805) 555-0101"), "+18055550101")
        self.assertEqual(phone_e164("805.555.0101 ext. 4"), "+18055550101")
        self.assertEqual(phone_e164("1-805-555-0101 x123"), "+18055550101")
        self.assertEqual(phone_e164("+44 20 7946 0958"), "+442079460958")
        self.assertIsNone(phone_e164("055 555 0101"))
        self.assertIsNone(phone_e164("555-0101"))
        self.assertIsNone(phone_e164(None))

    def test_ascii_length_boundaries(self):
        self.assertEqual(phone_e164("+2234567"), "+2234567")  # shortest accepted
        self.assertIsNone(phone_e164("+223456"))
        self.assertEqual(phone_e164("+" + "2" * 15), "+" + "2" * 15)  # longest accepted
        self.assertIsNone(phone_e164("+" + "2" * 16))
        for text in ("+442079460958", "8055550101", "+1 805 555 0101"):
            result = phone_e164(text)
            assert result is not None
            self.assertTrue(re.fullmatch(r"\+[0-9]+", result))


if __name__ == "__main__":
    unittest.main()
