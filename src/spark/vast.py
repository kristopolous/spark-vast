"""Thin async client for the Vast.ai REST API.

Paths and payloads mirror the official `vastai` CLI and
https://docs.vast.ai/api-reference/.
"""

from typing import Any

import httpx

from . import __version__
from .config import VAST_API_URL, VAST_ROUTE_URL, get_api_key
from .exceptions import VastAPIError

USER_AGENT = f"spark-vast/{__version__}"


class VastClient:
    def __init__(self, api_key: str | None = None, base_url: str = VAST_API_URL):
        self.api_key = api_key or get_api_key()
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )

    async def __aenter__(self) -> "VastClient":  # noqa: PYI034
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        resp = await self._http.request(method, url, **kwargs)
        if resp.status_code >= 400:
            body = resp.text[:500]
            hint = ""
            if resp.status_code in (401, 403):
                hint = " (check your API key: `spark login`)"
            raise VastAPIError(
                f"{method} {path} -> HTTP {resp.status_code}{hint}: {body}",
                status=resp.status_code,
                body=body,
            )
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError as e:
            raise VastAPIError(f"{method} {path} returned non-JSON: {resp.text[:200]}") from e
        if isinstance(data, dict) and data.get("success") is False:
            raise VastAPIError(f"{method} {path} failed: {data.get('msg') or data.get('error') or data}")
        return data

    # ---- offers / instances -------------------------------------------------

    async def search_offers(self, query: dict) -> list[dict]:
        data = await self._request("POST", "/bundles/", json=query)
        return data.get("offers", [])

    async def create_instance(self, offer_id: int, body: dict) -> int:
        data = await self._request("PUT", f"/asks/{offer_id}/", json={"client_id": "me", **body})
        return int(data["new_contract"])

    async def show_instance(self, instance_id: int) -> dict | None:
        try:
            data = await self._request("GET", f"/instances/{instance_id}/", params={"owner": "me"})
        except VastAPIError as e:
            if e.status == 404:
                return None
            raise
        inst = data.get("instances", data) if isinstance(data, dict) else None
        return inst or None

    async def list_instances(self) -> list[dict]:
        data = await self._request("GET", "/instances/", params={"owner": "me"})
        return data.get("instances", [])

    async def destroy_instance(self, instance_id: int) -> None:
        try:
            await self._request("DELETE", f"/instances/{instance_id}/")
        except VastAPIError as e:
            if e.status != 404:
                raise

    # ---- templates / serverless --------------------------------------------

    async def create_template(self, body: dict) -> dict:
        data = await self._request("POST", "/template/", json=body)
        return data.get("template", data)

    async def create_endpoint(self, body: dict) -> int:
        data = await self._request("POST", "/endptjobs/", json={"client_id": "me", **body})
        return int(data.get("result", data.get("id")))

    async def list_endpoints(self) -> list[dict]:
        data = await self._request("GET", "/endptjobs/")
        return data.get("results", [])

    async def delete_endpoint(self, endpoint_id: int) -> None:
        await self._request("DELETE", f"/endptjobs/{endpoint_id}/")

    async def create_workergroup(self, body: dict) -> int:
        data = await self._request("POST", "/workergroups/", json={"client_id": "me", **body})
        return int(data["id"])

    async def route(self, endpoint_name: str, cost: float = 100.0) -> dict:
        return await self._request("POST", VAST_ROUTE_URL, json={"endpoint": endpoint_name, "cost": cost})
