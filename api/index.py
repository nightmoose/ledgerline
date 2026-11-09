"""Vercel entry. The app stays in mock mode unless the host sets LEDGERLINE_MODE=live."""

from ledgerline.main import app

__all__ = ["app"]
