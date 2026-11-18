"""Keep the saved ship-queue reference in sync; do not read live protection."""

import json
import re
import unittest

from tests._support import ROOT

# The non-browser pairs match the retained read-only protection receipt.
# The browser jobs use the same Actions app as the former unsharded job.
ACTIONS_APP_ID = 15368
NON_BROWSER_CHECKS = ("survey-science", "check (3.13)", "sign-off")


def _block(text, key, indent):
    # Read only the nested block mappings used by ci.yml, not arbitrary YAML.
    pad = " " * indent
    lines = iter(text.splitlines())
    if not any(re.fullmatch(rf"{pad}{key}: *(?:#.*)?", line) for line in lines):
        raise AssertionError(f"Expected the {key!r} block in ci.yml")
    children = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(pad + " "):
            break
        children.append(line)
    return "\n".join(children)


class RequiredChecksTests(unittest.TestCase):
    def test_saved_contexts_match_browser_matrix_and_keep_receipted_checks(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        browser = _block(_block(workflow, "jobs", 0), "e2e", 2)
        # GitHub names an unnamed, single-axis matrix job <job-id> (<value>).
        self.assertNotRegex(browser, r"(?m)^    (?:name|'name'|\"name\") *:", "Review changed e2e job names")
        matrix = _block(_block(browser, "strategy", 4), "matrix", 6)
        shards = re.fullmatch(r"        shard: *(\[[^\n]*\]) *(?:#.*)?", matrix)
        if shards is None:
            self.fail("Review the e2e context names if the shard matrix changes shape")
        shard_numbers = json.loads(shards[1])
        self.assertTrue(shard_numbers and all(type(n) is int and n > 0 for n in shard_numbers))
        self.assertEqual(len(shard_numbers), len(set(shard_numbers)), "Duplicate e2e shard")

        names = [*NON_BROWSER_CHECKS, *(f"e2e ({n})" for n in shard_numbers)]
        expected = [{"context": name, "app_id": ACTIONS_APP_ID} for name in names]
        manifest = json.loads((ROOT / ".github/required-checks.json").read_text(encoding="utf-8"))
        checks = manifest["required_checks"]
        self.assertTrue(all(type(check["app_id"]) is int for check in checks), "Expected integer app IDs")
        self.assertCountEqual(checks, expected)
