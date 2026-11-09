"""Vercel entry. The app stays in mock mode unless the host sets LEDGERLINE_MODE=live."""

import sys
from pathlib import Path

# Vercel does not install the package itself, so put src/ on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledgerline.main import app  # noqa: E402

__all__ = ["app"]
