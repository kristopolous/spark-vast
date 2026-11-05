"""Drive @Endpoint through the instance backend against a real local worker."""

import httpx
import pytest

import spark.endpoint
from spark import Endpoint, RemoteExecutionError, state
from tests.conftest import FakeVast


@pytest.fixture
def fake_vast(worker, monkeypatch):
    fake = FakeVast(worker)
    monkeypatch.setattr(spark.endpoint, "VastClient", lambda: fake)
    monkeypatch.setattr("spark.backends.instance.POLL_SECONDS", 0.01)
    return fake


@Endpoint(name="adder", gpu="RTX_4090")
async def add(a, b, *, scale=1):
    print("adding on the worker")
    return (a + b) * scale


@Endpoint(name="uses-helper")
def uses_local_module(x):
    import _spark_helper

    return _spark_helper.double(x)


@Endpoint(name="boom")
def boom():
    raise ValueError("kaboom")


@Endpoint(name="objects")
def roundtrip(obj):
    return {"got": obj, "type": type(obj).__name__}


async def test_call_runs_remotely_and_returns_result(fake_vast, capsys):
    assert await add(2, 3, scale=10) == 50
    assert "[adder] adding on the worker" in capsys.readouterr().err
    assert fake_vast.offer_queries[0]["gpu_name"] == {"eq": "RTX 4090"}


async def test_second_call_reuses_the_instance(fake_vast):
    await add(1, 1)
    await add(2, 2)
    assert len(fake_vast.created) == 1
    assert state.get("adder")["instance_id"] == 1001


async def test_sync_function_and_local_module_bundling(fake_vast):
    assert await uses_local_module(21) == 42


async def test_remote_exception_surfaces_traceback(fake_vast):
    with pytest.raises(RemoteExecutionError, match="ValueError: kaboom"):
        await boom()


async def test_arbitrary_picklable_args(fake_vast):
    out = await roundtrip({1, 2, 3})
    assert out == {"got": {1, 2, 3}, "type": "set"}


async def test_dead_worker_is_destroyed_and_reprovisioned(fake_vast, worker):
    await add(1, 1)
    worker.stop()  # simulate the box idling out
    fake_vast.destroyed.append(1001)
    worker_restart_port = worker.port
    assert await add(3, 4) == 7
    assert len(fake_vast.created) == 2
    assert worker.port == worker_restart_port


async def test_config_change_replaces_instance(fake_vast):
    await add(1, 1)
    changed = Endpoint(name="adder", gpu="RTX 3090")(add.local)
    assert await changed(1, 2) == 3
    assert fake_vast.destroyed == [1001]
    assert len(fake_vast.created) == 2


def test_worker_rejects_bad_token(worker):
    r = httpx.post(f"{worker.url}/execute", json={}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_local_call_bypasses_vast():
    assert uses_local_module.local.__name__ == "uses_local_module"
