"""Pre-import guard for a reviewed project source tree; never imports the project."""
import os
import stat


def guard_project_source(package_root):
    """Refuse project bytecode and symlinks before the first project import.

    This scans only the caller's trusted skippercast package tree. Standard
    library and installed dependency trees are outside this guard. It is a
    source-only deployment check, not a filesystem sandbox or import hook.
    """
    root = os.path.abspath(os.fspath(package_root))
    if not stat.S_ISDIR(os.lstat(root).st_mode):
        raise ValueError("trusted project source root must be a regular directory")
    def walk_error(error):
        raise ValueError("project source tree cannot be checked") from error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs + files:
            path = os.path.join(directory, name)
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("project source symlink/compiled bytecode forbidden")
            if name == "__pycache__" or name.endswith((".pyc", ".pyo")):
                raise ValueError("project compiled bytecode forbidden")
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("project source special file forbidden")
    return root
