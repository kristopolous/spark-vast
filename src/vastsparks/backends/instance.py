"""On-demand backend: one rented Vast instance per endpoint, called directly.

Cheapest option and fully under your control: the instance is reused across
calls, destroys itself after `idle_timeout` seconds without work, and
`vastsparks down` removes it immediately.
"""

import asyncio
import logging
import secrets
import time

import httpx

from .. import state
from ..exceptions import ProvisioningError, VastAPIError
from ..protocol import FunctionRequest, FunctionResponse
from ..resources import EndpointConfig
from ..vast import VastClient
from ..worker import instance_onstart, packed_server
from .base import Backend, StaleResourceError

log = logging.getLogger(__name__)

WORKER_PORT = 8000
POLL_SECONDS = 5
DEAD_STATUSES = {"exited", "offline", "destroyed", "deleted"}


def worker_url(inst: dict) -> str | None:
    """http://ip:port for the worker, once Vast has mapped the port."""
    ip = inst.get("public_ipaddr")
    mappings = (inst.get("ports") or {}).get(f"{WORKER_PORT}/tcp") or []
    if not ip or not mappings:
        return None
    return f"http://{ip.strip()}:{mappings[0]['HostPort']}"


class InstanceBackend(Backend):
    name = "instance"

    async def ensure(self, cfg: EndpointConfig, vast: VastClient) -> dict:
        entry = state.get(cfg.name)
        if entry and entry.get("backend") == self.name:
            if entry.get("config_hash") == cfg.config_hash():
                inst = await vast.show_instance(entry["instance_id"])
                if inst and inst.get("actual_status") not in DEAD_STATUSES:
                    return await self._wait_ready(cfg, entry, vast)
                log.info("%s: instance %s is gone; renting a new one", cfg.name, entry["instance_id"])
            else:
                log.info("%s: config changed; replacing instance %s", cfg.name, entry["instance_id"])
                await self.teardown(entry, vast)
            state.remove(cfg.name)
        elif entry:
            raise ProvisioningError(
                f"'{cfg.name}' is deployed with the {entry.get('backend')} backend; "
                f"run `vastsparks down {cfg.name}` first"
            )
        return await self._wait_ready(cfg, await self._rent(cfg, vast), vast)

    async def _rent(self, cfg: EndpointConfig, vast: VastClient) -> dict:
        offers = await vast.search_offers(cfg.offer_query())
        if not offers:
            raise ProvisioningError(
                f"No Vast offers match {cfg.name}: gpu={cfg.gpus or 'any'} x{cfg.num_gpus}, "
                f"disk>={cfg.disk_gb}GB, max ${cfg.max_price_per_hour}/hr. "
                "Try `vastsparks offers` with looser filters."
            )

        token = secrets.token_urlsafe(32)
        body = {
            "image": cfg.image,
            "disk": cfg.disk_gb,
            "label": f"vastsparks-{cfg.name}",
            "runtype": "ssh_direc ssh_proxy",
            "onstart": instance_onstart(),
            "env": {
                f"-p {WORKER_PORT}:{WORKER_PORT}": "1",
                "VASTSPARKS_TOKEN": token,
                "VASTSPARKS_PORT": str(WORKER_PORT),
                "VASTSPARKS_IDLE_TIMEOUT": str(cfg.idle_timeout),
                "VASTSPARKS_WORKER_B64": packed_server(),
                **cfg.env,
            },
        }

        errors = []
        for offer in offers[:5]:  # cheap offers get taken; fall through a few
            try:
                instance_id = await vast.create_instance(offer["id"], body)
            except VastAPIError as e:
                errors.append(f"offer {offer['id']}: {e}")
                continue
            entry = {
                "backend": self.name,
                "instance_id": instance_id,
                "token": token,
                "config_hash": cfg.config_hash(),
                "gpu": offer.get("gpu_name"),
                "num_gpus": offer.get("num_gpus"),
                "dph_total": offer.get("dph_total"),
                "created_at": time.time(),
                "url": None,
            }
            state.put(cfg.name, entry)  # record before waiting so `vastsparks down` can clean up
            log.info(
                "%s: rented instance %s (%s x%s @ $%.3f/hr)",
                cfg.name,
                instance_id,
                offer.get("gpu_name"),
                offer.get("num_gpus"),
                offer.get("dph_total") or 0,
            )
            return entry
        raise ProvisioningError("Could not rent any matching offer:\n" + "\n".join(errors))

    async def _wait_ready(self, cfg: EndpointConfig, entry: dict, vast: VastClient) -> dict:
        deadline = time.monotonic() + cfg.provision_timeout
        last_msg = None
        async with httpx.AsyncClient(timeout=10) as http:
            while time.monotonic() < deadline:
                if entry.get("url") and await _healthy(http, entry["url"]):
                    return entry

                inst = await vast.show_instance(entry["instance_id"])
                if inst is None:
                    raise ProvisioningError(f"instance {entry['instance_id']} disappeared")
                status = inst.get("actual_status")
                if status in DEAD_STATUSES:
                    raise ProvisioningError(
                        f"instance {entry['instance_id']} is {status}: {inst.get('status_msg')}"
                    )
                msg = f"{status or 'pending'}: {(inst.get('status_msg') or '').strip()[:120]}"
                if msg != last_msg:
                    log.info("%s: %s", cfg.name, msg)
                    last_msg = msg

                url = worker_url(inst) if status == "running" else None
                if url and url != entry.get("url"):
                    entry["url"] = url
                    state.put(cfg.name, entry)
                await asyncio.sleep(POLL_SECONDS)

        raise ProvisioningError(
            f"{cfg.name}: worker not ready after {cfg.provision_timeout}s "
            f"(instance {entry['instance_id']} is still running and billing; "
            f"`vastsparks down {cfg.name}` to remove it)"
        )

    async def execute(
        self, cfg: EndpointConfig, entry: dict, req: FunctionRequest, vast: VastClient
    ) -> FunctionResponse:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(cfg.request_timeout, connect=15)) as http:
                resp = await http.post(
                    f"{entry['url']}/execute",
                    json=req.model_dump(),
                    headers={"Authorization": f"Bearer {entry['token']}"},
                )
        except httpx.ConnectError as e:
            # Most likely the box idled out and destroyed itself.
            raise StaleResourceError(str(e)) from e
        if resp.status_code == 401:
            raise StaleResourceError("worker rejected our token (instance was replaced?)")
        resp.raise_for_status()
        return FunctionResponse(**resp.json())

    async def teardown(self, entry: dict, vast: VastClient) -> None:
        await vast.destroy_instance(entry["instance_id"])


async def _healthy(http: httpx.AsyncClient, url: str) -> bool:
    try:
        return (await http.get(f"{url}/health")).status_code == 200
    except httpx.HTTPError:
        return False
