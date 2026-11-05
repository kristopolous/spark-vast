"""Vast Serverless backend: endpoint + workergroup, autoscaled by Vast.

Each worker runs the spark worker behind Vast's PyWorker. Calls go through
`run.vast.ai/route`, which picks a ready worker and signs the request.
Better for bursty or multi-user traffic; you pay for whatever cold/hot
workers the autoscaler keeps.

EXPERIMENTAL: built from the public docs; the worker request envelope
(auth_data/payload) and the PyWorker package name have not yet been
checked against a live endpoint.
"""

import asyncio
import logging
import time

import httpx

from .. import state
from ..exceptions import ProvisioningError, VastAPIError
from ..protocol import FunctionRequest, FunctionResponse
from ..resources import EndpointConfig
from ..vast import VastClient
from ..worker import packed_pyworker, packed_server, serverless_onstart
from .base import Backend, StaleResourceError

log = logging.getLogger(__name__)

ROUTE_POLL_SECONDS = 5


def vast_endpoint_name(name: str) -> str:
    return f"spark-{name}"


class ServerlessBackend(Backend):
    name = "serverless"

    async def ensure(self, cfg: EndpointConfig, vast: VastClient) -> dict:
        entry = state.get(cfg.name)
        if entry and entry.get("backend") == self.name:
            if entry.get("config_hash") == cfg.config_hash():
                return entry
            log.info("%s: config changed; recreating serverless endpoint", cfg.name)
            await self.teardown(entry, vast)
            state.remove(cfg.name)
        elif entry:
            raise ProvisioningError(
                f"'{cfg.name}' is deployed with the {entry.get('backend')} backend; "
                f"run `spark down {cfg.name}` first"
            )

        env = " ".join(
            [
                f"-e SPARK_WORKER_B64={packed_server()}",
                f"-e SPARK_PYWORKER_B64={packed_pyworker()}",
                *(f"-e {k}={v}" for k, v in cfg.env.items()),
            ]
        )
        template = await vast.create_template(
            {
                "name": f"spark-{cfg.name}-{cfg.config_hash()}",
                "image": cfg.image,
                "env": env,
                "onstart": serverless_onstart(cfg.pyworker_pip),
                "runtype": "ssh",
                "use_ssh": True,
                "ssh_direct": True,
                "jup_direct": False,
                "use_jupyter_lab": False,
                "extra_filters": {
                    k: v for k, v in cfg.offer_query().items() if k not in ("order", "type", "limit")
                },
                "recommended_disk_space": cfg.disk_gb,
            }
        )
        template_hash = template.get("hash_id")
        if not template_hash:
            raise ProvisioningError(f"Vast did not return a template hash: {template}")

        endpoint_id = await vast.create_endpoint(
            {
                "endpoint_name": vast_endpoint_name(cfg.name),
                "min_load": cfg.min_load,
                "target_util": cfg.target_util,
                "cold_mult": 2.0,
                "cold_workers": cfg.cold_workers,
                "max_workers": cfg.max_workers,
            }
        )
        entry = {
            "backend": self.name,
            "endpoint_id": endpoint_id,
            "endpoint_name": vast_endpoint_name(cfg.name),
            "template_hash": template_hash,
            "config_hash": cfg.config_hash(),
            "created_at": time.time(),
        }
        state.put(cfg.name, entry)

        entry["workergroup_id"] = await vast.create_workergroup(
            {
                "endpoint_id": endpoint_id,
                "template_hash": template_hash,
                "search_params": cfg.search_params_string(),
                "gpu_ram": cfg.min_gpu_ram_gb or 8,
                "test_workers": 1,
                "cold_workers": cfg.cold_workers,
                "max_workers": cfg.max_workers,
            }
        )
        state.put(cfg.name, entry)
        log.info(
            "%s: created Vast endpoint %s (workergroup %s)", cfg.name, endpoint_id, entry["workergroup_id"]
        )
        return entry

    async def execute(
        self, cfg: EndpointConfig, entry: dict, req: FunctionRequest, vast: VastClient
    ) -> FunctionResponse:
        deadline = time.monotonic() + cfg.provision_timeout
        last_status = None
        while True:
            try:
                route = await vast.route(entry["endpoint_name"])
            except VastAPIError as e:
                if e.status in (400, 404):
                    raise StaleResourceError(str(e)) from e
                raise
            if route.get("url"):
                break
            status = route.get("status")
            if status != last_status:
                log.info("%s: waiting for a ready worker (%s)", cfg.name, status)
                last_status = status
            if time.monotonic() > deadline:
                raise ProvisioningError(
                    f"{cfg.name}: no serverless worker ready after {cfg.provision_timeout}s "
                    f"(last status: {status})"
                )
            await asyncio.sleep(ROUTE_POLL_SECONDS)

        auth_data = {k: v for k, v in route.items() if k != "status"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(cfg.request_timeout, connect=15)) as http:
            resp = await http.post(
                f"{route['url'].rstrip('/')}/execute",
                json={"auth_data": auth_data, "payload": req.model_dump()},
            )
        resp.raise_for_status()
        return FunctionResponse(**resp.json())

    async def teardown(self, entry: dict, vast: VastClient) -> None:
        try:
            await vast.delete_endpoint(entry["endpoint_id"])  # also removes its workergroups
        except VastAPIError as e:
            if e.status != 404:
                raise
