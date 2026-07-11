"""Configuration loader: thin YAML reader with dot-style access.

Keeps things simple — no Pydantic validation, no envvar interpolation. The
config schema is documented in config/default.yaml; if you mistype a key,
you'll get an AttributeError at the point of use, which is fine for a teaching MVP.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class Config:
    """Recursive dot-access wrapper around a YAML dict."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name not in self._data:
            raise AttributeError(f"Config has no key {name!r}; available: {list(self._data)}")
        v = self._data[name]
        return Config(v) if isinstance(v, dict) else v

    def __getitem__(self, key: str) -> Any:
        return self.__getattr__(key)

    def get(self, key: str, default: Any = None) -> Any:
        v = self._data.get(key, default)
        return Config(v) if isinstance(v, dict) else v

    def to_dict(self) -> dict[str, Any]:
        return self._data


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as f:
        return Config(yaml.safe_load(f))
