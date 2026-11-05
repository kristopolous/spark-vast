"""Local record of what spark has provisioned on Vast.ai (~/.spark/state.json).

Each entry is keyed by endpoint name and holds the Vast ids needed to reuse
or tear down the resource. Writes are atomic and guarded by a file lock so
several processes can share it.
"""

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .config import spark_home


def _path() -> Path:
    return spark_home() / "state.json"


@contextlib.contextmanager
def _locked() -> Iterator[dict[str, Any]]:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except ValueError:
            data = {}
        before = json.dumps(data, sort_keys=True)
        yield data
        if json.dumps(data, sort_keys=True) != before:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
            os.chmod(tmp, 0o600)  # holds per-instance worker tokens
            tmp.replace(path)


def get(name: str) -> dict | None:
    with _locked() as data:
        return data.get(name)


def put(name: str, entry: dict) -> None:
    with _locked() as data:
        data[name] = entry


def remove(name: str) -> None:
    with _locked() as data:
        data.pop(name, None)


def all_entries() -> dict[str, dict]:
    with _locked() as data:
        return dict(data)
