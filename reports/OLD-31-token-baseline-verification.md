# OLD-31: token baseline verification (audit D.2, line 128)

Audit row: "Duplicate CSS (`packages/coast/panel.css` 2.9 k) vs `web/tokens.css`. Token lint baseline exists; shrink via the baseline, not a rewrite."

Checked against skippercast `origin/main` = `0991fc70d212c9405f7b174950cb3fa4d7c6846d` (the spec was written against `351e321dd`; the results are the same).

**Result: no CSS change; row closed as already satisfied (baselines empty).**

## 1. The four token-lint scopes pass with an empty baseline

```console
$ node scripts/check_tokens.mjs
Token lint passed: 301 files, 0 finding(s), all in the baseline (0 entries left to fix) [web].
Token lint passed: 59 files, 0 finding(s), all in the baseline (0 entries left to fix) [packages/coast].
Token lint passed: 4 files, 0 finding(s), all in the baseline (0 entries left to fix) [dist/advisor].
Token lint passed: 1 files, 0 finding(s), all in the baseline (0 entries left to fix) [dist/coast-readable.css].
```

```console
$ cat scripts/token-lint-coast-baseline.json
{
 "note": "Literals that predate the token lint (scripts/check_tokens.mjs). This list only shrinks: replace the literal with a var(--…) token, then run `node scripts/check_tokens.mjs --update`. Never add entries.",
 "entries": [
 ]
}
```

## 2. `panel.css` holds no colour literals

```console
$ grep -cE "#[0-9a-fA-F]{3,8}\b" packages/coast/panel.css
0
$ grep -cE "var\(--coast-[a-z0-9-]+, *(#|rgb|hsl)" packages/coast/panel.css
0
$ wc -l packages/coast/panel.css web/tokens.css
 2948 packages/coast/panel.css
  226 web/tokens.css
 3174 total
```

`panel.css` is 2,948 lines (audit: about 2,930). The baseline has zero entries and the file has zero hex literals and zero literal fallbacks, so there is nothing left to shrink through the baseline. Whether `panel.css` repeats whole rule blocks (structural, not token, duplication) is a different question that the audit row does not ask; "not a rewrite" rules it out here.

## 3. Negative control: the empty baseline still bites

Scratch copy of `packages/`, `web/`, `dist/advisor`, `dist/coast-readable.css` and the baselines in `/tmp`, run with `TOKEN_LINT_ROOT` (as `tests/test_check_tokens.mjs` does). Never committed.

Unmodified copy: all four scopes pass, exit 0. After appending `.old31-negative-control { color: #fff; }` to the scratch `panel.css`:

```console
Token lint: 1 new finding(s). Write var(--coast-…) without a fallback and map the role in packages/coast/tokens-bridge.css; renderer colours belong in packages/coast/src/palette.ts. Do not add these ...
  packages/coast/panel.css:2949 [colour-literal] :host{display:block;color:var(--coast-text);...
```

The lint fails on one new literal (the `[packages/coast]` scope prints no pass line) and the other scopes still pass.

## 4. Tests

```console
$ node --test tests/test_check_tokens.mjs tests/test_coast_fallbacks.mjs
# tests 32
# suites 0
# pass 31
# fail 0
# cancelled 0
# skipped 1
```

The one skip is "production inventory: pinned production CLI pass/fail without baseline writes", gated by `{skip: !process.env.COAST_INVENTORY_FIXTURE}`. It is skipped unless that env var points at an inventory fixture. It is an environment-gated test, not a failure.

## 5. Scope

This PR adds this one file. No CSS, baseline, test or generated file is touched; `--update` was not run.
