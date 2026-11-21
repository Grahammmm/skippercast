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


# The four browser shards are separate jobs (not a matrix) so a job-level `if` can skip them
# while each still reports its own `e2e (N)` context.
SHARD_JOB_IDS = ("e2e", "e2e-2", "e2e-3", "e2e-4")


class RequiredChecksTests(unittest.TestCase):
    def test_saved_contexts_match_browser_shard_jobs_and_keep_receipted_checks(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        jobs = _block(workflow, "jobs", 0)
        shard_numbers = []
        for job_id in SHARD_JOB_IDS:
            job = _block(jobs, job_id, 2)
            self.assertNotIn("matrix:", job, f"{job_id} must stay one explicit shard job")
            name = re.search(r"(?m)^    name: *(.+?) *$", job)
            shard = re.search(r"(?m)^      SHARD: *'(\d+)' *$", job)
            if name is None or shard is None:
                self.fail(f"{job_id} needs an explicit name and its SHARD env for its required context")
            self.assertEqual(name[1], f"e2e ({shard[1]})", f"{job_id} context must match its shard")
            shard_numbers.append(int(shard[1]))
        self.assertEqual(shard_numbers, list(range(1, len(SHARD_JOB_IDS) + 1)), "Shards must be 1..N in order")
        # Every shard shares one step list, whose divisor must equal the shard count.
        self.assertIn(f'pnpm e2e --shard="$SHARD/{len(SHARD_JOB_IDS)}"', _block(jobs, "e2e", 2))

        names = [*NON_BROWSER_CHECKS, *(f"e2e ({n})" for n in shard_numbers)]
        expected = [{"context": name, "app_id": ACTIONS_APP_ID} for name in names]
        manifest = json.loads((ROOT / ".github/required-checks.json").read_text(encoding="utf-8"))
        checks = manifest["required_checks"]
        self.assertTrue(all(type(check["app_id"]) is int for check in checks), "Expected integer app IDs")
        self.assertCountEqual(checks, expected)
