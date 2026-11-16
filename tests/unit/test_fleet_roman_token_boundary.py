"""roman_to_int refuses malformed tokens (final newline included) with None, never KeyError."""
import unittest

from skippercast.fleet.normalize import name_norm, roman_to_int

_ONES = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
_TENS = ["", "X", "XX", "XXX"]


class RomanTokenBoundaryTests(unittest.TestCase):
    def test_final_newline_is_an_invalid_token_not_a_key_error(self):
        for token in ("I\n", "IV\n", "X\n", "XXXIX\n", "iv\n"):
            with self.subTest(token=token):
                self.assertIsNone(roman_to_int(token))

    def test_whitespace_and_noncanonical_numerals_stay_invalid(self):
        for token in ("", " ", " IV", "IV ", "IV\r\n", "I\nV", "IIII", "VX", "XL", "MIX", "40"):
            with self.subTest(token=token):
                self.assertIsNone(roman_to_int(token))

    def test_valid_one_through_thirty_nine_and_lowercase(self):
        # Expected values come from an independent tens/ones table, not the helper.
        for tens, tens_text in enumerate(_TENS):
            for ones, ones_text in enumerate(_ONES):
                if tens == 0 and ones == 0:
                    continue
                text = tens_text + ones_text
                with self.subTest(token=text):
                    self.assertEqual(roman_to_int(text), tens * 10 + ones)
                    self.assertEqual(roman_to_int(text.lower()), tens * 10 + ones)

    def test_vessel_name_normalization_does_not_drift(self):
        cases = {
            "F/V Example IV": "EXAMPLE4",
            "Example XXXIX": "EXAMPLE39",
            "X": "X",
            "New Example IV": "NEWEXAMPLE4",
            "Example IV\n": "EXAMPLE4",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(name_norm(name), expected)


if __name__ == "__main__":
    unittest.main()
