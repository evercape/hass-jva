"""Put the controller library on the import path.

Home Assistant only installs this component folder. The same modules live in
the repo's src tree during development, and in bundled/ for a HACS install.
"""

from __future__ import annotations

import sys
from pathlib import Path

_LOADED = False


def load_library() -> None:
    global _LOADED
    if _LOADED:
        return
    component = Path(__file__).resolve().parent
    repo_src = component.parents[1] / "src"
    if (repo_src / "jva_fence" / "client.py").is_file():
        entry = str(repo_src)
    else:
        entry = str(component / "bundled")
    if entry not in sys.path:
        sys.path.insert(0, entry)
    _LOADED = True
