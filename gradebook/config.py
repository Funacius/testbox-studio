"""Level 2 reads every application URL and element locator from JSON."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_site(level: int, config_path: Path | None = None) -> dict:
    if level == 1:
        from level1.settings import SITE
        site = deepcopy(SITE)
    elif level == 2:
        path = config_path or ROOT / "level2/config/site.json"
        site = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("Level must be 1 or 2")
    for key in ("base_url", "course_id", "urls", "locators", "grade_types", "timeout"):
        if key not in site:
            raise ValueError(f"Site configuration is missing {key}")
    return site
