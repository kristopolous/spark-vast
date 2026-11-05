"""cloudpickle + base64 helpers (client side)."""

import base64
from typing import Any

import cloudpickle

from .exceptions import PayloadTooLargeError, SerializationError

MAX_PAYLOAD_SIZE = 64 * 1024 * 1024  # 64 MB of base64 text per value


def serialize_arg(arg: Any) -> str:
    try:
        data = base64.b64encode(cloudpickle.dumps(arg)).decode("ascii")
    except Exception as e:
        raise SerializationError(f"Failed to serialize argument: {e}") from e
    if len(data) > MAX_PAYLOAD_SIZE:
        raise PayloadTooLargeError(
            f"Serialized argument is {len(data) / 2**20:.1f} MB, over the "
            f"{MAX_PAYLOAD_SIZE / 2**20:.0f} MB limit. Pass a URL or path instead."
        )
    return data


def serialize_args(args: tuple) -> list[str]:
    return [serialize_arg(a) for a in args]


def serialize_kwargs(kwargs: dict) -> dict[str, str]:
    return {k: serialize_arg(v) for k, v in kwargs.items()}


def deserialize(data: str) -> Any:
    try:
        return cloudpickle.loads(base64.b64decode(data))
    except Exception as e:
        raise SerializationError(f"Failed to deserialize result: {e}") from e
