import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

WORKER = Path(__file__).resolve().parents[1] / "src" / "vastsparks" / "worker" / "server.py"


@pytest.fixture(autouse=True)
def vastsparks_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VASTSPARKS_HOME", str(tmp_path / "vastsparks_home"))
    monkeypatch.setenv("VAST_API_KEY", "test-key")
    return tmp_path / "vastsparks_home"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalWorker:
    def __init__(self, token: str = "tok"):
        self.token = token
        self.port = _free_port()
        self.proc: subprocess.Popen | None = None

    def start(self) -> "LocalWorker":
        env = {
            **os.environ,
            "VASTSPARKS_TOKEN": self.token,
            "VASTSPARKS_PORT": str(self.port),
            "VASTSPARKS_HOST": "127.0.0.1",
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-I", str(WORKER)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        for _ in range(100):
            try:
                if httpx.get(f"{self.url}/health").status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.05)
        raise RuntimeError("worker did not start")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait(5)
            self.proc = None


@pytest.fixture
def worker():
    w = LocalWorker().start()
    yield w
    w.stop()


class FakeVast:
    """Stands in for VastClient: 'rents' instances that point at a local worker."""

    def __init__(self, worker: LocalWorker):
        self.worker = worker
        self.created: list[dict] = []
        self.destroyed: list[int] = []
        self.offer_queries: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def search_offers(self, query):
        self.offer_queries.append(query)
        return [{"id": 111, "gpu_name": "RTX 4090", "num_gpus": 1, "dph_total": 0.35}]

    async def create_instance(self, offer_id, body):
        self.created.append(body)
        self.worker.token = body["env"]["VASTSPARKS_TOKEN"]
        self.worker.stop()
        self.worker.start()  # restart with the token vastsparks generated
        return 1000 + len(self.created)

    async def show_instance(self, instance_id):
        if instance_id in self.destroyed:
            return None
        return {
            "id": instance_id,
            "actual_status": "running",
            "public_ipaddr": "127.0.0.1\n",
            "ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(self.worker.port)}]},
        }

    async def destroy_instance(self, instance_id):
        self.destroyed.append(instance_id)
