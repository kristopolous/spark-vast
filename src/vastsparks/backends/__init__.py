from ..resources import Backend as BackendKind
from .base import Backend, StaleResourceError
from .instance import InstanceBackend
from .serverless import ServerlessBackend

_BACKENDS: dict[str, Backend] = {
    BackendKind.INSTANCE.value: InstanceBackend(),
    BackendKind.SERVERLESS.value: ServerlessBackend(),
}


def get_backend(kind: str | BackendKind) -> Backend:
    key = kind.value if isinstance(kind, BackendKind) else kind
    try:
        return _BACKENDS[key]
    except KeyError:
        raise ValueError(f"unknown backend {kind!r}; choose one of {sorted(_BACKENDS)}") from None


__all__ = ["Backend", "InstanceBackend", "ServerlessBackend", "StaleResourceError", "get_backend"]
