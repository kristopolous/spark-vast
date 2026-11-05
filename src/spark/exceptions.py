"""Spark exception types."""


class SparkError(Exception):
    """Base class for all spark errors."""


class ConfigError(SparkError):
    """Missing or invalid configuration (e.g. no Vast API key)."""


class VastAPIError(SparkError):
    """The Vast.ai REST API returned an error."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class ProvisioningError(SparkError):
    """Could not rent or start a worker."""


class RemoteExecutionError(SparkError):
    """The remote function raised, or the worker could not run it."""


class SerializationError(SparkError):
    """cloudpickle could not (de)serialize a value."""


class PayloadTooLargeError(SerializationError):
    """A serialized payload exceeds the size limit."""


class LocalModuleResolutionError(SparkError):
    """A local import of an endpoint function cannot be bundled."""


class LocalModulePayloadTooLargeError(SparkError):
    """Bundled local module source exceeds the inline cap."""
