"""RF1130-9: ft/m/kt/nmi conversion literals live only in skippercast/util/units.py and the named ALLOW list."""
import ast
import io
import tempfile
import tokenize
import unittest
from pathlib import Path

from tests._support import ROOT

SRC, OWNER, LIVE = ROOT / "src" / "skippercast", "util/units.py", "live loop"
# Compared by value: .3048, 1852.0 and 1_852 match; 18520, 0.30481 and 3.280841 do not.
VALUES = {float(s) for s in "3.28084 3.280839895 3.2808398950131 1.94384449 1.943844492 1.9438444924406 0.3048 1.852 1852".split()}
ALLOW = {  # path under src/skippercast -> why its literal stays; delete the entry when the module reads util.units
    **{f"pipeline/{name}.py": LIVE for name in ("cdip_nearshore", "coast_report", "coast_snapshots", "intelligence",
                                                "ndbc_history", "ocean", "verification", "wave_ensemble")},
    **{f"{name}.py": "offline .3048 spelling, migration not yet specced" for name in (
        "coastal/render/terrain_only", "coastal/vertical", "platform/bottom_targets", "platform/qualified_scope",
        "seafloor/habitat", "seafloor/search_areas")},
    "monitor/collector.py": "held legacy monitor", "platform/depth_contours.py": "builder data constant mirrored by packages/coast",
    "fleet/ais/match.py": "fleet matcher kept 3.28084 by RF0708-1 (1/0.3048 flips its 20 % length verdict)",
}


def scan(root, allow=ALLOW):  # failure messages for the package tree at root; [] means clean
    problems = [f"remove {rel} from ALLOW (no such file)" for rel in sorted(allow) if not (root / rel).is_file()]
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        try:  # NUMBER tokens only, so comments and strings never match
            ast.parse(text := path.read_text(encoding="utf-8"))
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            lines = [t.start[0] for t in tokens if t.type == tokenize.NUMBER and ast.literal_eval(t.string) in VALUES]
        except (UnicodeDecodeError, SyntaxError, ValueError, tokenize.TokenError) as exc:
            problems.append(f"{rel}: cannot scan ({type(exc).__name__})")
            continue
        if rel in allow and not lines:
            problems.append(f"remove {rel} from ALLOW (no conversion literal left)")
        elif rel not in allow and rel != OWNER:
            problems += [f"{rel}:{n}: ft/m/kt/nmi literal outside {OWNER}; import it from skippercast.util.units" for n in lines]
    return problems


class UnitsGuardTests(unittest.TestCase):
    def tree(self, files, allow=None):
        with tempfile.TemporaryDirectory() as tmp:
            for rel, body in files.items():
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / rel).write_bytes(body if isinstance(body, bytes) else body.encode())
            return scan(Path(tmp), allow or {})

    def test_main_is_clean(self):
        self.assertEqual(scan(SRC), [])

    def test_planted_literal_named_by_file_and_line(self):
        self.assertEqual(self.tree({"pkg/a.py": "y = 1\nx = v * 0.3048\n", OWNER: "M_PER_FT = 0.3048\n"}),
                         [f"pkg/a.py:2: ft/m/kt/nmi literal outside {OWNER}; import it from skippercast.util.units"])

    def test_comments_strings_and_longer_numbers_pass_but_respellings_do_not(self):
        src = ('# 0.3048 m per ft\ns = "1852"\n"""3.28084"""\na = 18520\nb = 3.280841\nc = 0.30481\nd = 1852.0\ne = 1_852\n'
               'f = 0x1852\ng = 1852j\nh = .3048\n')
        self.assertEqual([p.split(":")[1] for p in self.tree({"a.py": src})], ["7", "8", "11"])

    def test_allowlisted_file_without_literal_must_leave_allow(self):
        allow = {"p/live.py": LIVE, "p/still.py": LIVE, "p/gone.py": LIVE}
        self.assertEqual(self.tree({"p/live.py": "x = 1\n", "p/still.py": "KT = 1.943844492\n"}, allow),
                         ["remove p/gone.py from ALLOW (no such file)", "remove p/live.py from ALLOW (no conversion literal left)"])

    def test_undecodable_or_broken_file_is_a_named_failure(self):
        found = self.tree({"bad.py": b"x = '\xff'\n", "broken.py": "def f(:\n    return 0.3048\n", "ok.py": "x = 1\n"})
        self.assertEqual(found, ["bad.py: cannot scan (UnicodeDecodeError)", "broken.py: cannot scan (SyntaxError)"])
