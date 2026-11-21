# Relative Markdown link audit

| Result | Offline scan, 2026-11-21 (PT) |
| --- | ---: |
| Markdown files scanned | 412 (405 under `docs/`, 7 at the root) |
| Markdown links found | 3,066 |
| Relative links checked | 1,570 |
| Broken file targets | 0 |
| Missing Markdown anchors | 7 (all in one ADR; see R2) |

## R1. Counts and rules

Source: staged `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c`. No network checks. With the task's uncommitted `scan_links.py` beside a clean checkout of that commit, run `python3 scan_links.py skippercast` (Markdown-it-py 3.0.0). Cross-check the file count at the baseline with `git ls-files '*.md' | grep -E '^(docs/|[^/]+\.md$)' | wc -l`.

- Count occurrences, not distinct URLs. Parse inline links, resolved reference links and angle-bracket autolinks, including table cells. Ignore fenced and indented code blocks, inline code, comments, plain-text URLs, unreferenced definitions and raw HTML links/media. The separate HTML image at `README.md:7` resolves to the tracked `docs/images/skippercast-map.png` (`git ls-files -- docs/images/skippercast-map.png`). No Markdown image tokens were found.
- Skip external links (HTTP(S), other schemes and protocol-relative URLs): 1,496 occurrences. Skip slash-rooted URLs (none found). Expand percent escapes, ignore the query for path lookup and resolve paths relative to the source file against tracked files and directories, with case-sensitive matching. A fragment-only or empty destination uses the source page.
- For a nonempty fragment on an existing Markdown file, compare against rendered heading IDs and explicit HTML IDs/named anchors. The offline heading rule uses parsed ATX/Setext heading text, lowercases it, drops punctuation except hyphens and underscores, turns spaces into hyphens and numbers duplicate IDs (`-1`, `-2`, …). This models repository Markdown, not a live renderer check. Of the 220 Markdown fragments checked, 213 matched and 7 did not. Nine other fragments are code line locators on non-Markdown files (`docs/engineering/adr/0010-spot-alert-events.md:8,16,18–19,23–24`): their files exist; their fragments are not counted as Markdown headings.

Read-only scan output (2026-11-21): `docs 405`, `root 7`, `link 3066`, `external_link 1496`, `checked_link 1570`, `md_fragment 220`, `missing_anchor 7`, `non_md_fragment 9`; the missing-file counter produced no entries. Both Fish examples still exist at this base: `git ls-files -- docs/FISH-MERGE-STATUS.md docs/plans/fish-bridge-retirement.md`. The archive's link at `docs/archive/fish/README.md:17` resolves to the first file.

## R2. Every broken relative link

No missing-path rows. All seven fragments below use source line numbers in links to rendered Markdown, not heading IDs. The “existing file” column is the exact resolved file (no filename guess). The cited destination lines exist; changing how to reach them is outside this report. No live GitHub behavior is asserted.

| Source file:line | Link text | Target as written | Nearest existing file by name |
| --- | --- | --- | --- |
| `docs/engineering/adr/0010-spot-alert-events.md:17` | inventory row | `../../operations/runbooks/d1-restore.md#L25` | `docs/operations/runbooks/d1-restore.md:25` |
| `docs/engineering/adr/0010-spot-alert-events.md:17` | row-count query entry | `../../operations/runbooks/d1-restore.md#L121` | `docs/operations/runbooks/d1-restore.md:121` |
| `docs/engineering/adr/0010-spot-alert-events.md:17` | `DROP TABLE` statement | `../../operations/runbooks/d1-restore.md#L219` | `docs/operations/runbooks/d1-restore.md:219` |
| `docs/engineering/adr/0010-spot-alert-events.md:19` | trip event retention rule | `../../operations/runbooks/d1-restore.md#L25` | `docs/operations/runbooks/d1-restore.md:25` |
| `docs/engineering/adr/0010-spot-alert-events.md:28` | data model and recommended event storage | `../../research/specs/03-spot-water-alerts/plan.md#L14-L28` | `docs/research/specs/03-spot-water-alerts/plan.md:14–28` |
| `docs/engineering/adr/0010-spot-alert-events.md:29` | Roadmap owner gates | `../../research/specs/README.md#L15` | `docs/research/specs/README.md:15` |
| `docs/engineering/adr/0010-spot-alert-events.md:29` | ADR status rules | `0001-record-architecture-decisions.md#L37-L41` | `docs/engineering/adr/0001-record-architecture-decisions.md:37–41` |

## R3. Existing checks

- **File existence: yes.** `scripts/check_repository.py:23,179–186` scans `.md` text with a regular expression, skips URLs with a scheme/host or no path, percent-decodes the path, and fails for missing targets or paths outside the repo. It does not parse code fences, reference links or heading IDs. `.github/workflows/ci.yml:385–386` runs the checker. At the baseline, `python scripts/check_repository.py` passed on 2026-11-21: “Checked 6555 text files: local Markdown links, release privacy rules and the Text Advisor and charter fleet fixture scans passed.”
- **Tests: yes for paths, not anchor resolution.** `tests/unit/test_check_repository.py:260–304` exercises existing/missing paths, external URLs, root/parent escapes and percent-encoded paths. The fixture at line 300 passes a `#section` link without defining that heading. `research/tests/test_research_page_links.py:37–43,53–77` checks which links the research page renderer emits, unique heading IDs, and generated-page parity, not whether each Markdown link lands on a heading. The offline search below found no general Markdown anchor-resolution test.

```sh
git grep -ilE 'github.slug|heading.slug|fragment.{0,35}(heading|markdown)|anchor.{0,25}heading|linkcheck|check.markdown.links|MarkdownLinkTests|HeadingIdTest' -- .github scripts tests e2e research/tests
```

## R4. One optional follow-up (estimate: 30–60 minutes)

In a separate, approved docs-only unit, edit only `docs/engineering/adr/0010-spot-alert-events.md:17,19,28–29`: point the seven links to existing rendered sections and retain the exact line citations as text where they help the reader. Check the new fragments against headings in the four existing files in R2, rerun the same offline scan on the proposed checkout (set the scratch script's baseline pin to its head), and run `python scripts/check_repository.py`. Expect zero missing file targets and Markdown anchors. No additional file-existence guard is needed (R3). No links, policies or owner decisions were changed by this audit.
