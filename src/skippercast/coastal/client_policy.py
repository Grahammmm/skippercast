"""Packaged client freshness bound; no scheduler or caller policy overrides."""
from .coordinator.stages import digest

POLICY = {"schema": "coastal-client-heartbeat-policy-v1", "tick_interval_s": 30,
          "maximum_missed_ticks": 2, "cleanup_s": 5}


def heartbeat_detail(root, db, identities):
    return {"schema": "coastal-client-heartbeat-v1", "policy_sha256": digest(POLICY),
            "root_sha256": digest(str(root.resolve(strict=True))),
            "db_sha256": digest(str(db.resolve(strict=True))),
            "code_sha": identities[0], "deps_sha": identities[1]}
