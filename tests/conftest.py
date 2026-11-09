from pathlib import Path

import pytest

from ledgerline.config import load_settings
from ledgerline.service import Service

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def service(tmp_path: Path) -> Service:
    settings = load_settings(
        {
            "LEDGERLINE_MODE": "mock",
            "LEDGERLINE_MODEL_PROVIDER": "offline",
            "AIRWALLEX_ENV": "demo",
            "LEDGERLINE_LIMITS": str(ROOT / "policy" / "limits.yaml"),
            "LEDGERLINE_DATA_DIR": str(tmp_path),
        }
    )
    built = Service(settings)
    yield built
    built.close()
