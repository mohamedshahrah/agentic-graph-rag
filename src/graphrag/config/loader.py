"""Load configuration by deep-merging YAML profiles, then reading secrets from env.

Order (last wins):  configs/default.yaml  <  configs/<profile>.yaml  <  env vars
The profile name comes from GRAPHRAG_PROFILE (default: "api").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from graphrag.config.settings import Secrets, Settings
from graphrag.core.errors import ConfigError


def _default_config_dir() -> Path:
    """Locate `configs/` without assuming where the package lives.

    In a source checkout this file is `<repo>/src/graphrag/config/loader.py`, so
    the profiles sit three levels up. Installed (site-packages) that walk lands
    outside the project entirely, so fall back to the working directory. The
    Docker image pins GRAPHRAG_CONFIG_DIR rather than relying on either guess.
    """
    checkout = Path(__file__).resolve().parents[3] / "configs"
    return checkout if checkout.is_dir() else Path.cwd() / "configs"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file is not a mapping: {path}")
    return data


def load_settings(
    profile: str | None = None, config_dir: Path | None = None
) -> tuple[Settings, Secrets]:
    """Return the resolved (Settings, Secrets). Secrets carries API keys / URLs."""
    secrets = Secrets()
    profile = profile or secrets.profile
    cfg_dir = config_dir or secrets.config_dir or _default_config_dir()

    merged = _read_yaml(cfg_dir / "default.yaml")
    profile_path = cfg_dir / f"{profile}.yaml"
    if profile_path.exists():
        merged = _deep_merge(merged, _read_yaml(profile_path))

    try:
        settings = Settings(**merged)
    except Exception as exc:  # pydantic ValidationError -> our error type
        raise ConfigError(f"Invalid configuration: {exc}") from exc

    return settings, secrets
