import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import dotbot  # noqa: F401
except ModuleNotFoundError:
    local_dotbot_src = REPO_ROOT.parent / "dotbot" / "src"
    if local_dotbot_src.is_dir() and str(local_dotbot_src) not in sys.path:
        sys.path.insert(0, str(local_dotbot_src))
