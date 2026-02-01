import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PYTHON_PATHS = [
    ROOT / "apps" / "core-api",
    ROOT / "apps" / "agent-worker",
    ROOT / "packages" / "protocol",
    ROOT / "packages" / "runtime",
    ROOT / "packages" / "memory",
    ROOT / "packages" / "kb",
    ROOT / "packages" / "skills",
    ROOT / "packages" / "mcp",
]

for path in PYTHON_PATHS:
    sys.path.insert(0, str(path))
