"""Vastsparks exception types."""


class VastsparksError(Exception):
    """Base class for all vastsparks errors."""


class ConfigError(VastsparksError):
    """Missing or invalid configuration (e.g. no Vast API key)."""


class VastAPIError(VastsparksError):
    """The Vast.ai REST API returned an error."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class ProvisioningError(VastsparksError):
    """Could not rent or start a worker."""


class RemoteExecutionError(VastsparksError):
    """The remote function raised, or the worker could not run it."""


class SerializationError(VastsparksError):
    """cloudpickle could not (de)serialize a value."""


class PayloadTooLargeError(SerializationError):
    """A serialized payload exceeds the size limit."""


class LocalModuleResolutionError(VastsparksError):
    """A local import of an endpoint function cannot be bundled."""


class LocalModulePayloadTooLargeError(VastsparksError):
    """Bundled local module source exceeds the inline cap."""
