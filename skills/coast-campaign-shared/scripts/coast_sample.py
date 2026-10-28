"""coast-sample-v1 deterministic, clamped reference implementation."""
import hashlib
import json
import argparse


def window_key(source_id, grid_sha256, idx):
    if not isinstance(source_id, str) or not source_id or type(idx) is not int or idx < 0:
        raise ValueError("invalid source/index")
    if len(grid_sha256) != 64 or any(c not in "0123456789abcdef" for c in grid_sha256):
        raise ValueError("invalid grid SHA256")
    return f"{source_id}#{grid_sha256}#{idx}"


def window_dir(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def sample(map_done, eligible, *, plan_sha256, bridge_sha256):
    """Callers must prove eligibility from verified Tier1 + all Tier2 checks.

    Both populations are explicit unique window keys. Missing/held/unavailable
    evidence cannot be declared eligible by this deterministic selection function.
    """
    done, clean = list(map_done), list(eligible)
    if len(set(done)) != len(done) or len(set(clean)) != len(clean):
        raise ValueError("duplicate sample population")
    if not set(clean) <= set(done) or any(not isinstance(k, str) or not k for k in done):
        raise ValueError("eligible must be a subset of map_done window keys")
    for digest in (plan_sha256, bridge_sha256):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid sample binding SHA256")
    seed = hashlib.sha256(f"{plan_sha256}:{bridge_sha256}".encode()).hexdigest()
    target = max(8, (len(done) + 7) // 8)
    size = min(target, len(clean))
    ranked = sorted(clean, key=lambda k: (hashlib.sha256(f"{seed}:{k}".encode()).hexdigest(), k))
    return dict(method_version="coast-sample-v1", seed=seed, target=target, size=size,
                map_done=sorted(done), eligible=sorted(clean), selected=sorted(ranked[:size]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON containing map_done/eligible/plan_sha256/bridge_sha256")
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as stream:
        values = json.load(stream)
    print(json.dumps(sample(**values), sort_keys=True, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
