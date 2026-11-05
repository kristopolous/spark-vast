"""The @Endpoint decorator: run a local Python function on a Vast.ai GPU."""

import asyncio
import functools
import inspect
import logging
import sys
import weakref
from collections.abc import Callable
from typing import Any

from . import state
from .backends import StaleResourceError, get_backend
from .compat import ServerlessResource, flash_to_vastsparks
from .exceptions import RemoteExecutionError
from .protocol import FunctionRequest, FunctionResponse
from .resources import EndpointConfig
from .serialization import deserialize, serialize_args, serialize_kwargs
from .source import build_modules_map, get_function_source
from .vast import VastClient

log = logging.getLogger(__name__)

# One provisioning lock per (event loop, endpoint name) so concurrent calls in
# one process share a single rented box instead of each renting their own.
_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


def _lock(name: str) -> asyncio.Lock:
    per_loop = _locks.setdefault(asyncio.get_running_loop(), {})
    return per_loop.setdefault(name, asyncio.Lock())


class RemoteFunction:
    """A function that runs on Vast.ai when awaited.

    `await fn(...)` runs remotely; `fn.local(...)` calls the original
    function in-process; `fn.sync(...)` is a blocking convenience.
    """

    def __init__(self, func: Callable, config: EndpointConfig):
        functools.update_wrapper(self, func)
        self.local = func
        self.config = config

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        req = self._build_request(args, kwargs)
        backend = get_backend(self.config.backend)
        cfg = self.config

        async with VastClient() as vast:
            for attempt in (1, 2):
                async with _lock(cfg.name):
                    entry = await backend.ensure(cfg, vast)
                try:
                    resp = await backend.execute(cfg, entry, req, vast)
                    break
                except StaleResourceError as e:
                    if attempt == 2:
                        raise RemoteExecutionError(f"{cfg.name}: worker unavailable: {e}") from e
                    log.info("%s: worker unavailable (%s); re-provisioning", cfg.name, e)
                    await backend.teardown(entry, vast)  # idempotent; never leak a billing box
                    state.remove(cfg.name)

        return self._handle_response(resp)

    def sync(self, *args: Any, **kwargs: Any) -> Any:
        return asyncio.run(self(*args, **kwargs))

    def _build_request(self, args: tuple, kwargs: dict) -> FunctionRequest:
        source = get_function_source(self.local)
        original = inspect.unwrap(self.local)
        return FunctionRequest(
            function_name=original.__name__,
            function_code=source,
            args=serialize_args(args),
            kwargs=serialize_kwargs(kwargs),
            dependencies=self.config.dependencies,
            system_dependencies=self.config.system_dependencies,
            modules=build_modules_map(source, original.__globals__.get("__file__")),
        )

    def _handle_response(self, resp: FunctionResponse) -> Any:
        for line in (resp.stdout or "").splitlines():
            print(f"[{self.config.name}] {line}", file=sys.stderr)
        if not resp.success:
            raise RemoteExecutionError(f"{self.config.name} failed remotely:\n{resp.error}")
        return deserialize(resp.result) if resp.result is not None else None


class Endpoint:
    """Decorator that turns a function into a Vast.ai-backed RemoteFunction.

    Accepts runpod-flash's arguments (gpu=GpuGroup.ADA_24, workers=(0, 3),
    gpu_count, idle_timeout, execution_timeout_ms, min_cuda_version,
    datacenter, ...) as well as vastsparks's (backend, max_price_per_hour,
    min_gpu_ram_gb, search, ...). See vastsparks.compat for the mapping.

    Example:
        @Endpoint(name="hello-gpu", gpu=GpuType.NVIDIA_GEFORCE_RTX_4090, dependencies=["torch"])
        async def hello():
            import torch
            return torch.cuda.get_device_name(0)

        print(asyncio.run(hello()))

    `name` defaults to the function name.
    """

    def __init__(self, name: str | None = None, *, id: str | None = None, **config: Any):
        if id is not None:
            raise NotImplementedError(
                "Endpoint(id=...) connects to an existing Runpod endpoint; vastsparks has no equivalent yet"
            )
        self.name = name
        self.config = flash_to_vastsparks(config)

    def __call__(self, func: Callable) -> RemoteFunction:
        if inspect.isclass(func):
            raise TypeError(
                "vastsparks @Endpoint supports functions only (class endpoints are not ported yet)"
            )
        cfg = EndpointConfig(name=self.name or func.__name__.replace("_", "-"), **self.config)
        return RemoteFunction(func, cfg)

    # Flash's load-balanced route decorators and client-mode calls.
    def _unsupported(self, *_: Any, **__: Any):
        raise NotImplementedError(
            "vastsparks supports queue-style @Endpoint functions only; load-balanced routes "
            "(.get/.post/...) and client calls (.run/.runsync/.status) are not ported yet"
        )

    get = post = put = patch = delete = run = runsync = status = _unsupported


def remote(
    resource_config: Any = None,
    dependencies: list[str] | None = None,
    system_dependencies: list[str] | None = None,
    accelerate_downloads: bool = True,
    local: bool = False,
    method: str | None = None,
    path: str | None = None,
    **config: Any,
):
    """runpod-flash's `@remote(resource_config=LiveServerless(...), ...)`, plus bare `@remote`.

    Vastsparks-style keywords (`@remote(gpu="RTX 4090")`) also work.
    """
    if callable(resource_config) and not isinstance(resource_config, ServerlessResource):
        return Endpoint()(resource_config)  # bare @remote
    if method or path:
        raise NotImplementedError(
            "vastsparks does not support load-balanced @remote(method=, path=) routes yet"
        )

    kw: dict[str, Any] = {}
    name = config.pop("name", None)
    if resource_config is not None:
        kw.update(resource_config.to_endpoint_kwargs())
        name = name or resource_config.name
    kw.update(config)
    if dependencies is not None:
        kw["dependencies"] = dependencies
    if system_dependencies is not None:
        kw["system_dependencies"] = system_dependencies

    def decorator(func: Callable):
        if local:
            return func  # Flash semantics: run in-process, no provisioning
        return Endpoint(name, **kw)(func)

    return decorator
