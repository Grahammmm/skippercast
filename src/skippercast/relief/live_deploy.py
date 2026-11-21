"""Offline verdicts for the deployment and pointer checks in a relief release."""

import re
from collections.abc import Callable


class LiveError(ValueError):
    """Invalid live-check input, reported without echoing the response."""


def parse_deploy(doc: object) -> str:
    """Extract the exact commit from a decoded deployment receipt."""
    commit = doc.get("commit") if isinstance(doc, dict) else None
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise LiveError("Expected a full lowercase hexadecimal deploy commit")
    return commit


def deploy_verdict(
    merge_sha: str,
    deployed_sha: str,
    is_ancestor: Callable[[str, str], bool | None],
) -> dict[str, str]:
    """Check the deployed history; an inconclusive ancestry lookup fails closed."""
    if merge_sha == deployed_sha:
        return {"check": "deploy", "status": "PASS", "reason": "equal"}

    contains_merge = is_ancestor(merge_sha, deployed_sha)
    if contains_merge is True:
        return {"check": "deploy", "status": "PASS", "reason": "ancestor"}

    if contains_merge is None:
        reason = "unknown-commit"
    else:
        deployed_is_older = is_ancestor(deployed_sha, merge_sha)
        if deployed_is_older is None:
            reason = "unknown-commit"
        else:
            reason = "stale" if deployed_is_older else "diverged"
    return {"check": "deploy", "status": "FAIL", "reason": reason}


def pointer_verdict(merged_bytes: bytes, served_bytes: bytes | None) -> dict[str, str]:
    """Compare raw pointer bytes, not their decoded JSON values."""
    if served_bytes is None:
        return {"check": "pointer", "status": "FAIL", "reason": "missing"}
    if served_bytes != merged_bytes:
        return {"check": "pointer", "status": "FAIL", "reason": "differs"}
    return {"check": "pointer", "status": "PASS", "reason": "identical"}
