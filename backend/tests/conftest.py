import os
from pathlib import Path

import pytest

os.environ["FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION"] = "true"
os.environ["FIXPROOF_SANDBOX_MODE"] = "local"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def auth_src() -> Path:
    return REPO_ROOT / "examples" / "buggy-python-app"


@pytest.fixture
def paginate_src() -> Path:
    return REPO_ROOT / "examples" / "paginate-app"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
