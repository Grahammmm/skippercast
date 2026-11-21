# Brief and Conditions Spanish catalogue: checkpoint

**Recommendation:** Allow one English wording exception for the spear verdict, then plan all six rows as one catalogue change. (`modes/NEXT-BACKLOG-2026-11-20-skippercast-2137-r2.tsv:13`, operator backlog)
**Why stop here:** The English verdict still says `choppy chop`; the Spanish wording is already `oleaje corto picado`. Keeping all English output byte-identical would keep the defect. (`packages/coast/src/spear.ts:185`, `web/brief/verdict-copy.ts:76–82,105`, `tests/test_verdict_i18n.mjs:217–226`)
**Source checked:** Main at `7335068efd2627dd2a0ba9bea39f09e86a8f252d` (`git rev-parse origin/main` → `7335068efd2627dd2a0ba9bea39f09e86a8f252d`).

## 1. What still appears in English (C1)

| Backlog row | What main does |
| --- | --- |
| SC2022-01 | Open. The desktop eyebrow prints `brief.label`; the printed place line uses the profile table's English label directly. The print date line already uses the language-aware day helper and is not the affected line. (`web/app/Desktop.tsx:45–51`, `web/brief/Brief.tsx:952–963`) |
| SC2022-02 | Open. The available fleet link and both local-report states print the model's English text. The separate unavailable fleet message already uses the catalogue; leave that branch alone. (`web/brief/Brief.tsx:917–926`, `web/brief/model.ts:37–41,197–198`) |
| SC2022-03 | Open. The disclosure heading is translated, but the list uses `brief.missing` verbatim. Nearby feed gaps use a different renderer. (`web/brief/Brief.tsx:885–899`, `packages/coast/src/daily.ts:214–253`) |
| SC2022-04 | Open. The lower-exposure label and selected reasons are model strings, including the custom-limits note when present. The eyebrow and no-window messages already use the catalogue. (`web/brief/Brief.tsx:855–866`, `packages/coast/src/daily.ts:188,263–270`, `packages/coast/src/limits.ts:95–101`) |
| SC2137-03 | Open. Conditions calls `moonLine` without a language; the formatter emits `Moon: {phase}, {percent}% lit` using English phase names. (`web/app/views/Conditions.tsx:115–116`, `web/moon.ts:11,19,57–60`) |
| SC2137-09 | English defect still open; not a missing Spanish translation. The grader produces `choppy chop`. Unlike the Spanish branch, the English branch returns the raw reason **before** the `{band} chop` catalogue lookup. The verdict joins the formatted reasons into its headline. (`packages/coast/src/spear.ts:178–187`, `web/brief/verdict-copy.ts:76–82,101–109`, `web/brief/verdict.ts:285`, `catalog/app/strings.json:245,256`) |

These are source findings. A deployed-site or browser replay is **UNVERIFIED**.

## 2. Copy decision needed (C2)

The approved spear row asks for English without the doubled word and for the Spanish wording and other reasons to stay byte-identical (`modes/NEXT-BACKLOG-2026-11-20-skippercast-2137-r2.tsv:13`, operator backlog). C2 instead asks for English byte-identical to today's text for every open row. Those instructions cannot both hold for this row. Changing the existing `verdict.reason.chop` template alone would not fix English, because the early return bypasses it (`web/brief/verdict-copy.ts:76–82,105`).

Recommended clarification: allow a new, placeholder-free verdict entry with English `choppy water` and Spanish `oleaje corto picado`; match only the exact raw `choppy chop` reason at display time before the English return. Preserve the shared template, the Light and Rough output in both languages, and the grader's English input (`catalog/app/strings.json:245,256`, `web/brief/verdict-copy.ts:76–82,105`, `packages/coast/src/spear.ts:178–187`). This is a recommendation, not an approved copy block. The complete blocks and native-language review are **UNVERIFIED** at this stop.

## 3. Build plan held (C3)

The spear wording fix waits for SC1222-05, “The day verdict's reasons use the units you chose,” because both touch `web/brief/verdict-copy.ts` (`modes/NEXT-BACKLOG-2026-11-20-skippercast-2137-r2.tsv:13` and `modes/NEXT-BACKLOG-2026-11-18-skippercast-1222.tsv:9`, operator backlog). After the wording decision and once the catalogue is free, re-read that renderer and regenerate the tables from the single catalogue with `node scripts/build_landing_strings.mjs`; do not hand-merge generated tables (`scripts/build_landing_strings.mjs:9–17,43–59`). The full implementation plan, focused acceptance list and time budget are **UNVERIFIED**. No catalogue, generated table, product or test file is changed by this checkpoint.

## 4. Source replay (C4)

Run from the checkout root. On the report branch, the source paths are unchanged from the main commit named above.

```sh
git grep -n -F "if (lang === 'en') return raw;" -- web/brief/verdict-copy.ts
# web/brief/verdict-copy.ts:78:    if (lang === 'en') return raw;
git grep -n -F "'choppy chop': 'oleaje corto picado'" -- tests/test_verdict_i18n.mjs
# tests/test_verdict_i18n.mjs:219 matches the exact Spanish assertion values.
```
