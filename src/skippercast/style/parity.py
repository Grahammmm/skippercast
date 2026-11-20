"""Keys that bind the nearshore engine to the kit reference (STYLE-PIPELINE-DESIGN rev 3, 5.2).

``scripts/style/kit_parity.py`` writes ``OUT/_style/parity/<parity key>/parity.json``; the tiles
stage (provenance) and QA compute the same keys with these functions, so a parity result can
be found again and a stale one (other engine, epoch, runtime, look or kit) is never reused.
"""

from pathlib import Path
import platform
import re

from skippercast.relief import receipts

HEX64 = re.compile(r"[0-9a-f]{64}")
ENGINE_CODE = (("skippercast.relief.nearshore", "relief/nearshore.py"), ("skippercast.style", "style/__init__.py"))
RUNTIME_KEYS = ("numpy", "python", "scipy")
REFERENCE_FILES = ("compare.py", "requirements.txt", "skn_render.py")


def _hex64(name, value):
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256 hex digest")
    return value


def _runtime(runtime):
    if not isinstance(runtime, dict) or sorted(runtime) != sorted(RUNTIME_KEYS) \
            or not all(isinstance(v, str) and v for v in runtime.values()):
        raise ValueError(f"runtime must be exactly {{{', '.join(RUNTIME_KEYS)}}} version strings")
    return dict(runtime)


def engine_digest(package_root=None):
    """``receipts.stage_digest`` over the engine and the style loader (the code that makes pixels)."""
    root = Path(__file__).resolve().parents[1] if package_root is None else Path(package_root)
    return receipts.stage_digest([(label, root / path) for label, path in ENGINE_CODE])


def engine_runtime():
    """The interpreter and numeric libraries the engine renders with in this process."""
    import numpy
    import scipy
    return {"python": platform.python_version(), "numpy": numpy.__version__, "scipy": scipy.__version__}


def oracle_key(kit_zip_sha256, files_manifest_sha256, reference_sha256, runtime, args):
    """sha256 of the canonical oracle identity: kit bytes, reference code, kit venv, case arguments."""
    if sorted(reference_sha256) != sorted(REFERENCE_FILES):
        raise ValueError(f"reference_sha256 must name exactly {list(REFERENCE_FILES)}")
    if not isinstance(runtime, dict) or not runtime or not isinstance(args, dict) or not args:
        raise ValueError("oracle runtime and per-case args are required")
    return receipts.sha256_bytes(receipts.canonical({
        "kit_zip_sha256": _hex64("kit_zip_sha256", kit_zip_sha256),
        "files_manifest_sha256": _hex64("files_manifest_sha256", files_manifest_sha256),
        "reference_sha256": {name: _hex64(name, value) for name, value in reference_sha256.items()},
        "runtime": runtime, "args": args}))


def parity_key(engine_digest, engine_epoch, runtime, baked, kit_zip_sha256, files_manifest_sha256, oracle_key):
    """sha256 of the canonical parity identity (design 5.2)."""
    if not isinstance(engine_epoch, int) or isinstance(engine_epoch, bool) or engine_epoch < 1:
        raise ValueError("engine_epoch must be a positive integer")
    return receipts.sha256_bytes(receipts.canonical({
        "engine_digest": _hex64("engine_digest", engine_digest), "engine_epoch": engine_epoch,
        "runtime": _runtime(runtime), "baked": _hex64("baked", baked),
        "fixtures": {"kit_zip_sha256": _hex64("kit_zip_sha256", kit_zip_sha256),
                     "files_manifest_sha256": _hex64("files_manifest_sha256", files_manifest_sha256)},
        "oracle_key": _hex64("oracle_key", oracle_key)}))
