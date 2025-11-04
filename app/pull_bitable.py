"""Bridge module to load project-level pull_bitable.py inside app package.
This avoids relative import beyond top-level when running `python -m app.main`.
"""

import os
import importlib.util
import types

_ROOT_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "pull_bitable.py")
)

spec = importlib.util.spec_from_file_location("pull_bitable_root", _ROOT_FILE)
module = types.ModuleType("pull_bitable_root")
if spec and spec.loader:
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    # re-export public attributes
    for _name in dir(module):
        if not _name.startswith("_"):
            globals()[_name] = getattr(module, _name)


