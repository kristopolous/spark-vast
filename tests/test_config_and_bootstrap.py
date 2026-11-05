import base64
import gzip
import subprocess
from pathlib import Path

import httpx
import pytest

from spark.exceptions import VastAPIError
from spark.resources import EndpointConfig
from spark.vast import VastClient
from spark.worker import instance_onstart, packed_server

SERVER = Path(__file__).resolve().parents[1] / "src" / "spark" / "worker" / "server.py"


def test_offer_query_filters_and_orders_by_price():
    cfg = EndpointConfig(
        name="x",
        gpu=["RTX_4090", "RTX 3090"],
        max_price_per_hour=0.5,
        min_gpu_ram_gb=24,
        search={"geolocation": {"in": ["US"]}},
    )
    q = cfg.offer_query()
    assert q["gpu_name"] == {"in": ["RTX 4090", "RTX 3090"]}
    assert q["dph_total"] == {"lte": 0.5}
    assert q["gpu_ram"] == {"gte": 24 * 1024}
    assert q["order"] == [["dph_total", "asc"]]
    assert q["geolocation"] == {"in": ["US"]}
    assert "cuda_max_good" in q  # default image needs a recent driver


def test_search_params_string_uses_cli_syntax():
    s = EndpointConfig(name="x", gpu="RTX 4090").search_params_string()
    assert "gpu_name=RTX_4090" in s and "num_gpus=1" in s


def test_config_hash_ignores_dependencies_but_not_hardware():
    a = EndpointConfig(name="x", gpu="RTX 4090")
    assert a.config_hash() == EndpointConfig(name="x", gpu="RTX 4090", dependencies=["torch"]).config_hash()
    assert a.config_hash() != EndpointConfig(name="x", gpu="RTX 3090").config_hash()


def test_invalid_name_rejected():
    with pytest.raises(ValueError):
        EndpointConfig(name="bad name!")


def test_onstart_unpacks_worker_exactly(tmp_path):
    script = instance_onstart()
    unpack = next(line for line in script.splitlines() if "base64 -d" in line)
    subprocess.run(
        ["bash", "-c", unpack],
        cwd=tmp_path,
        check=True,
        env={"SPARK_WORKER_B64": packed_server(), "PATH": "/usr/bin:/bin"},
    )
    assert (tmp_path / "server.py").read_bytes() == SERVER.read_bytes()
    assert gzip.decompress(base64.b64decode(packed_server())) == SERVER.read_bytes()


async def test_vast_client_sends_bearer_and_maps_errors():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith("/bundles/"):
            return httpx.Response(200, json={"offers": [{"id": 1}]})
        if request.url.path.endswith("/asks/1/"):
            return httpx.Response(200, json={"success": True, "new_contract": 99})
        return httpx.Response(403, text="<html>403 Forbidden</html>")

    vast = VastClient(api_key="k")
    vast._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=vast._http.headers)
    assert await vast.search_offers({"q": 1}) == [{"id": 1}]
    assert await vast.create_instance(1, {"image": "x"}) == 99
    with pytest.raises(VastAPIError, match="spark login"):
        await vast.list_instances()
    await vast.aclose()

    assert seen[0].headers["authorization"] == "Bearer k"
    assert seen[0].headers["user-agent"].startswith("spark-vast/")
    assert seen[1].method == "PUT" and b'"client_id":"me"' in seen[1].content.replace(b" ", b"")
