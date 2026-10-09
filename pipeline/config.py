"""Configuration and path resolution."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class Config:
    settings: dict
    rules: dict
    fomc: dict
    overrides: dict
    data_dir: Path
    official_sources: dict | None = None

    @property
    def calc_version(self) -> str:
        return self.settings["calc_version"]


def load_config(data_dir: str | os.PathLike | None = None) -> Config:
    d = Path(data_dir or os.environ.get("PFI_DATA_DIR") or (REPO_ROOT / "data"))
    return Config(
        settings=_load("settings.json"),
        rules=_load("classification_rules.json"),
        fomc=_load("fomc_meetings.json"),
        overrides=_load("overrides.json"),
        data_dir=d,
        official_sources=_load("official_sources.json"),
    )
