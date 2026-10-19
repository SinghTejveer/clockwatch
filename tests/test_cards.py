"""The cards ship with the integration, and their version moves with it."""

from __future__ import annotations

import json
import re
from pathlib import Path

PKG = Path(__file__).parent.parent / "custom_components" / "clockwatch"


def test_the_cards_carry_the_integrations_version() -> None:
    version = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))["version"]
    js = (PKG / "www" / "clockwatch-cards.js").read_text(encoding="utf-8")
    assert re.search(r'const VERSION = "([^"]+)"', js).group(1) == version
    for tag in ("clockwatch-charge-card", "clockwatch-trip-card", "clockwatch-month-card"):
        assert f'define("{tag}"' in js


def test_brand_icons_are_there() -> None:
    assert (PKG / "brand" / "icon.png").stat().st_size > 1000 and (PKG / "brand" / "icon@2x.png").stat().st_size > 1000
