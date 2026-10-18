# Owners and path reservations

The coordinator is the single source of assignment confirmation. Before editing, ask for the task, fresh accepted base, exact file paths, dependencies and attempt bound. The coordinator serializes simultaneous requests: the first **confirmed assignment**, not the first comment, owns the paths. A plain assignee or label is not a lock. No new lease service or token infrastructure is required.

Current reserved lanes:

| Lane | Reserved work | Release owner |
| --- | --- | --- |
| Flock | Existing Flock owner: export/occurrence/digestion bridge, mail trace, PR130, skill adoption, relevant records files/tests | Existing Flock publisher |
| Mapping | Existing mapping installer/publisher: package/skill adoption and original native-packet coordination | Existing SkipperCast publisher |
| Backup | Dedicated backup owner: backup/Hermes trial and its workspace/configuration | Dedicated owner and applicable host operator |
| Reunion | Existing Reunion publisher; no new picker/catalog/payment/database work assigned to Claude | Existing Reunion publisher |
| Audit handoff | Coordinator docs/audit preparation, independent review, then existing SkipperCast publisher | Existing SkipperCast publisher |

Proposed first Claude task: ENC recovery integration, only `web/map/chart.ts`, `web/map/engine.ts`, and `tests/test_map_layers.mjs`; a truthful `CHANGELOG.md` entry may be composed by the publisher. Its issue must record coordinator confirmation before source changes. Shared theme assertions in the test file must be preserved. Any newly conflicting owner stops integration until the coordinator sequences the changes.

Use a unique `claude/<task-scope>` branch and isolated worktree from confirmed current main. Never edit another owner's worktree, runner checkout, shared dependencies, branch or uncommitted changes. After another task changes a shared file, bind the new accepted head and obtain cumulative compatibility review; do not overwrite from an old patch.

If an owner goes stale, expiry or silence does not authorize takeover. The coordinator checks the existing branch/worktree, job handles and saved checkpoint, obtains a safe release or scoped stop, then reassigns. Preserve the old result and failed attempts. Concurrent release requests are serialized by the repository's one publisher. Claude may merge only its own eligible assigned PR after explicit task release-ownership transfer, independent approval and required checks. No transfer means handoff, not a second publisher.
