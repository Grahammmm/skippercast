"""Fill bits on nonfinal AIVDM fragments are refused before assembly (RF2311-9).

Pure parsing: synthetic sentences from the test-only encoder in test_fleet_local_nmea, a fixed
clock, no socket.
"""
import unittest

from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.sources.local_nmea import Assembler, MalformedSentence, decode, parse_sentence
from tests.unit.test_fleet_local_nmea import (BBOX, NOW_MS, armour, feed, make, position, sentence, single,
                                              two_fragments, type5)

SEA = (999000004, 9999999, "WDX0001", "SEA EXAMPLE", 37, (10, 5, 3, 3))
SEA_STATIC = AisStatic(999000004, NOW_MS, "SEA EXAMPLE", "WDX0001", 9999999, 37, 10, 5, 3, 3, "A", "local-nmea")


def padded_split(bits, at=145, seq="3"):
    """Armour each side of a split at bit ``at`` on its own: the first fragment declares padding."""
    (first, first_fill), (last, last_fill) = armour(bits[:at]), armour(bits[at:])
    return [sentence(first, first_fill, count=2, index=1, seq=seq), sentence(last, last_fill, count=2, index=2, seq=seq)]


def run(source, assembler, lines):
    out = []
    for line in lines:
        out += source._line(line, assembler, BBOX, None)
    return out


class NonfinalFillTest(unittest.TestCase):
    def test_nonfinal_fill_values_refuse(self):
        for count, index in ((2, 1), (3, 1), (3, 2)):
            for fill in range(1, 6):
                with self.subTest(count=count, index=index, fill=fill):
                    with self.assertRaisesRegex(MalformedSentence, "nonfinal fragment has fill bits"):
                        parse_sentence(sentence("55", fill, count=count, index=index, seq="1"))
            self.assertEqual(parse_sentence(sentence("55", 0, count=count, index=index, seq="1")).fill, 0)
        for fill in (6, -1):    # the existing range check, not the new one
            with self.subTest(fill=fill), self.assertRaisesRegex(MalformedSentence, "out of range"):
                parse_sentence(sentence("55", fill, count=2, index=2, seq="1"))

    def test_final_and_single_fill_stay_admitted(self):
        for fill in range(6):
            with self.subTest(fill=fill):
                self.assertEqual(parse_sentence(sentence("55", fill)).fill, fill)
                self.assertEqual(parse_sentence(sentence("55", fill, count=2, index=2, seq="1")).fill, fill)
                self.assertEqual(parse_sentence(sentence("55", fill, count=3, index=3, seq="1")).fill, fill)

    def test_two_fragment_type5_with_real_final_padding_decodes(self):
        first, last = two_fragments(type5(*SEA))
        self.assertEqual((parse_sentence(first).fill, parse_sentence(last).fill), (0, 2))
        self.assertEqual(feed(make(), [first, last]), [SEA_STATIC])


class CorruptedStaticTest(unittest.TestCase):
    def test_padded_type5_cannot_emit_a_corrupted_static(self):
        bits = type5(*SEA)
        first, last = padded_split(bits)
        self.assertEqual(parse_sentence(last).fill, 3)    # the final fragment's padding is valid; the first's is not
        errors = []
        source = make(on_malformed=errors.append)
        assembler = Assembler()
        self.assertEqual(run(source, assembler, [first, last]), [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MalformedSentence)
        self.assertEqual((source.counts["malformed"], source.counts["dropped_groups"]), (1, 1))   # the orphan final
        self.assertEqual(assembler.dropped, 1)
        # the same message armoured whole and split on a character boundary is the healthy control
        self.assertEqual(feed(make(), two_fragments(bits)), [SEA_STATIC])

    def test_bad_then_good_continues_with_or_without_callback(self):
        first, last = padded_split(type5(*SEA))
        good_first, good_last = two_fragments(type5(*SEA), seq="4")
        lines = [first, last, single(position(1, 999000001)), good_first, good_last]
        errors = []
        with_callback = make(on_malformed=errors.append)
        out = feed(with_callback, lines)
        self.assertEqual([type(r) for r in out], [AisPosition, AisStatic])
        self.assertEqual((out[0].mmsi, out[1]), (999000001, SEA_STATIC))
        self.assertEqual((len(errors), with_callback.counts["malformed"], with_callback.counts["dropped_groups"]), (1, 1, 1))
        silent = make()
        self.assertEqual(feed(silent, lines), out)
        self.assertEqual((silent.counts["malformed"], silent.counts["dropped_groups"]), (1, 1))


class ActiveGroupTest(unittest.TestCase):
    def setUp(self):
        self.lines = two_fragments(type5(*SEA))
        self.bad_first = sentence("55", 3, count=2, index=1, seq="3")
        self.bad_middle = sentence("55", 2, count=3, index=2, seq="3")

    def test_invalid_nonfinal_cannot_mutate_active_group(self):
        errors = []
        source = make(on_malformed=errors.append)
        assembler = Assembler()
        first, last = self.lines
        out = run(source, assembler, [first, self.bad_first, self.bad_middle, last])
        self.assertEqual(out, [SEA_STATIC])
        self.assertEqual((len(errors), assembler.dropped, source.counts["dropped_groups"]), (2, 0, 0))

    def test_rejected_first_cannot_seed_a_group(self):
        source = make()
        assembler = Assembler()
        self.assertEqual(run(source, assembler, [self.bad_first, self.lines[1]]), [])
        self.assertEqual((source.counts["malformed"], assembler.dropped), (1, 1))     # the orphan final only
        self.assertEqual(run(source, assembler, [self.lines[1]]), [])                  # still no group to complete
        self.assertEqual(assembler.dropped, 2)


class ValidInputUnchangedTest(unittest.TestCase):
    def test_zero_fill_intermediate_fragments_assemble(self):
        bits = type5(*SEA)
        payload, fill = armour(bits)
        parts = [payload[:20], payload[20:40], payload[40:]]
        lines = [sentence(parts[0], 0, count=3, index=1, seq="7"), sentence(parts[1], 0, count=3, index=2, seq="7"),
                 sentence(parts[2], fill, count=3, index=3, seq="7")]
        self.assertEqual(decode("".join(parts), fill)["name"], "SEA EXAMPLE")
        self.assertEqual(feed(make(), lines), [SEA_STATIC])


if __name__ == "__main__":
    unittest.main()
