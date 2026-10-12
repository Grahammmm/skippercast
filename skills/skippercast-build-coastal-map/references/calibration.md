# Audit a completed run

Give the independent reviewer only the run receipt, relevant diff and actual visual/check evidence. Ask it to identify:

- What visibly improved, what remains unsupported, and any blocking defect.
- Actions that consumed tokens or time without forward progress, with evidence.
- Whether worker context or settings caused rework, and the next effective setting.
- The smallest justified addition, deletion or correction to this skill.

Keep useful stable decisions. Remove superseded rules and duplicated guidance. Do not add a permanent gate for every isolated incident. Apply the correction after reviewing it; preserve user choices and repository requirements. Save the diff and reviewer findings with the receipt.

Reuse `scripts/model_trials.py` for optional local evidence:

```bash
python3 <skill>/scripts/model_trials.py record --ledger <local-trials.jsonl> \
  --task renderer-fix --fingerprint <input-revision> \
  --model gpt-6-luna --effort low --outcome pass --kind actual \
  --evidence <run-receipt>
python3 <skill>/scripts/model_trials.py report --ledger <local-trials.jsonl>
```

Add measured `--tokens`, `--elapsed-seconds` and `--rework` only when available. Requested model settings are not independently observed usage. Simulated workflow decisions do not demonstrate rendering ability. Compare actual tasks with similar inputs and acceptance checks; consider review time and rework as well as worker usage. Keep the last successful setting as a fallback. The summary does not certify a minimum or estimate subscription savings.
