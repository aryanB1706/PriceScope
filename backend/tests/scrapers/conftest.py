from pathlib import Path

import pytest
from bs4 import BeautifulSoup

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> str:
        return (FIXTURE_DIR / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def without_json_ld():
    def _strip(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            script.decompose()
        return str(soup)

    return _strip
