# Pre-change deploy candidate (main 65a0232a6)

Exact copies of three scripts as they were on main at
`65a0232a6` (Merge pull request #760), before the deploy gate learned to ship an
older checked ancestor. `.txt` keeps tooling from treating them as live scripts.

- `cloudflare_deploy.sh.txt`: `scripts/cloudflare_deploy.sh` (labels the Worker
  version and the D1 backup with `GITHUB_SHA`)
- `check_deploy_source.py.txt`: `scripts/check_deploy_source.py` (requires the
  candidate to be current main)
- `worker_versions.mjs.txt`: `scripts/worker_versions.mjs` (no `live-commit`)

`tests/integration/test_deploy_controller.py` builds a candidate checkout from
them and runs the deploy job's real steps against it, with this branch's
controller scripts. That checks that a newer workflow can deploy an older
checked commit without running that commit's guard and with the correct version
label. Compare with `git show 65a0232a6:scripts/<name>`; the test does this
whenever the commit is in the local clone.
