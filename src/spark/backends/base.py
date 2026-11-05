from abc import ABC, abstractmethod

from ..protocol import FunctionRequest, FunctionResponse
from ..resources import EndpointConfig
from ..vast import VastClient


class Backend(ABC):
    """Provisions Vast.ai capacity for an endpoint and runs requests on it."""

    name: str

    @abstractmethod
    async def ensure(self, cfg: EndpointConfig, vast: VastClient) -> dict:
        """Make sure capacity exists for *cfg*; return its state entry."""

    @abstractmethod
    async def execute(
        self, cfg: EndpointConfig, entry: dict, req: FunctionRequest, vast: VastClient
    ) -> FunctionResponse:
        """Run one request. Raise StaleResourceError if the capacity is gone."""

    @abstractmethod
    async def teardown(self, entry: dict, vast: VastClient) -> None:
        """Release everything recorded in *entry*."""


class StaleResourceError(Exception):
    """The recorded instance/endpoint no longer exists; re-provision."""
