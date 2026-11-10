import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def duel_page_props() -> dict:
    return json.loads((FIXTURES / "duel_summary.json").read_text())
