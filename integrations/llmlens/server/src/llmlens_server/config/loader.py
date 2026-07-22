"""Load config: configs/default.yaml < configs/<profile>.yaml < env vars.

The config directory is resolved in order: $LLMLENS_CONFIG_DIR, ./configs
(cwd — covers Docker, where the package is pip-installed into site-packages
but /app/configs is copied next to the workdir), then the repo checkout
relative to this file (editable installs / running from source)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from llmlens_server.config.settings import Secrets, Settings
from llmlens_server.core.errors import ConfigError

_REPO_CONFIG_DIR = Path(__file__).resolve().parents[4] / "configs"


def _default_config_dir() -> Path:
    env_dir = os.getenv("LLMLENS_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    cwd_dir = Path.cwd() / "configs"
    if (cwd_dir / "default.yaml").exists():
        return cwd_dir
    return _REPO_CONFIG_DIR


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
    secrets = Secrets()
    profile = profile or secrets.profile
    cfg_dir = config_dir or _default_config_dir()

    merged = _read_yaml(cfg_dir / "default.yaml")
    profile_path = cfg_dir / f"{profile}.yaml"
    if profile != "default" and profile_path.exists():
        merged = _deep_merge(merged, _read_yaml(profile_path))

    try:
        settings = Settings(**merged)
    except Exception as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
    return settings, secrets
