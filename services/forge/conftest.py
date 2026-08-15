"""Makes the shared package importable so `cd services/forge && pytest` just works.

`pip install -e packages/core` stays the real answer and is what CI does. This is the
fallback for a working copy where that install is missing or has quietly stopped
resolving — on macOS every .pth file in the venv here carries the UF_HIDDEN flag, and
Python 3.14's site module skips hidden .pth files, so the editable install's import hook
is never registered and `import crescent_core` fails with the package still marked
installed. Without this, the suite needs PYTHONPATH set by hand, which is why it went
unrun. Only touched when the import genuinely fails, so a real install always wins.
"""
import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parents[2] / "packages" / "core"

try:
    import crescent_core  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(_CORE))
