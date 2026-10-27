"""Absolute source-only bootstrap for the trusted supervisor and launch gate."""
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True

# Python -I excludes caller-controlled paths, but it still reads existing pyc.
# Load the shared source guard directly, without importing any project module.
bootstrap_dir = Path(__file__).absolute().parent
guard_path = bootstrap_dir / "_source_bootstrap.py"
guard_namespace = {"__name__": "_coastal_source_guard"}
exec(compile(guard_path.read_bytes(), str(guard_path), "exec"), guard_namespace)
package_root = bootstrap_dir.parent
guard_namespace["guard_project_source"](package_root)
sys.path.insert(0, str(package_root.parent))
runpy.run_module("skippercast.coastal.runner", run_name="__main__")
