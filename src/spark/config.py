"""Credentials and local paths."""

import os
from pathlib import Path

from .exceptions import ConfigError

VAST_API_URL = os.environ.get("VAST_API_URL", "https://console.vast.ai/api/v0")
VAST_ROUTE_URL = os.environ.get("VAST_ROUTE_URL", "https://run.vast.ai/route/")


def spark_home() -> Path:
    return Path(os.environ.get("SPARK_HOME", Path.home() / ".spark"))


def _key_files() -> list[Path]:
    return [
        spark_home() / "api_key",
        Path.home() / ".config" / "vastai" / "vast_api_key",  # written by `vastai set api-key`
        Path.home() / ".vast_api_key",  # older vastai CLI location
    ]


def get_api_key() -> str:
    key = os.environ.get("VAST_API_KEY", "").strip()
    if key:
        return key
    for path in _key_files():
        if path.is_file():
            key = path.read_text().strip()
            if key:
                return key
    raise ConfigError(
        "No Vast.ai API key found. Run `spark login`, set VAST_API_KEY, "
        "or create one at https://cloud.vast.ai/manage-keys/"
    )


def save_api_key(key: str) -> Path:
    path = spark_home() / "api_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip() + "\n")
    path.chmod(0o600)
    return path
