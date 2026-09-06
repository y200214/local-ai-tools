"""Repository-owned paths. Do not derive the root from a caller's nesting depth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
WEBUI_ASSETS = ROOT / "webui_tour" / "assets"
