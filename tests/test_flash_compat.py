"""Code written for runpod-flash should work after swapping the import."""

import pytest

import spark
from spark import (
    CpuInstanceType,
    CpuLiveServerless,
    CudaVersion,
    DataCenter,
    Endpoint,
    GpuGroup,
    GpuType,
    LiveLoadBalancer,
    LiveServerless,
    remote,
)
from spark.compat import VAST_GPU_NAMES, vast_gpu_names

FLASH_ALL = [
    "remote",
    "Endpoint",
    "LiveServerless",
    "CpuLiveServerless",
    "LiveLoadBalancer",
    "CpuLiveLoadBalancer",
    "LoadBalancerSlsResource",
    "CpuLoadBalancerSlsResource",
    "ServerlessEndpoint",
    "CpuServerlessEndpoint",
    "GpuGroup",
    "GpuType",
    "CpuInstanceType",
    "CudaVersion",
    "DataCenter",
    "PodTemplate",
    "NetworkVolume",
    "ServerlessScalerType",
    "ServerlessType",
    "CPU_DATACENTERS",
]


@pytest.mark.parametrize("name", FLASH_ALL)
def test_flash_public_names_importable(name):
    assert hasattr(spark, name)


def test_every_gpu_type_has_a_vast_name():
    assert set(VAST_GPU_NAMES) == {t for t in GpuType if t != GpuType.ANY}


def test_gpu_translation():
    assert vast_gpu_names(GpuType.NVIDIA_GEFORCE_RTX_4090) == ["RTX 4090"]
    assert vast_gpu_names([GpuGroup.ADA_24, GpuType.NVIDIA_GEFORCE_RTX_3090]) == ["RTX 4090", "RTX 3090"]
    assert vast_gpu_names(GpuGroup.ANY) is None
    assert vast_gpu_names("ADA_24") == ["RTX 4090"]
    assert vast_gpu_names("RTX_4090") == ["RTX 4090"]


def test_readme_example_from_flash():
    @Endpoint(name="hello-gpu", gpu=GpuType.NVIDIA_GEFORCE_RTX_4090, dependencies=["torch"])
    async def hello():
        return 1

    cfg = hello.config
    assert cfg.gpus == ["RTX 4090"] and cfg.dependencies == ["torch"]
    assert cfg.offer_query()["gpu_name"] == {"eq": "RTX 4090"}


def test_endpoint_flash_kwargs_map_to_vast_filters():
    @Endpoint(
        name="w",
        gpu=GpuGroup.AMPERE_80,
        workers=(1, 4),
        gpu_count=2,
        idle_timeout=120,
        min_cuda_version=CudaVersion.V12_8,
        datacenter=[DataCenter.EU_RO_1],
        execution_timeout_ms=5000,
        flashboot=True,
        scaler_value=4,
    )
    def f():
        pass

    c = f.config
    assert c.gpus == ["A100 PCIE", "A100 SXM4"]
    assert (c.num_gpus, c.cold_workers, c.max_workers, c.idle_timeout) == (2, 1, 4, 120)
    assert c.min_cuda == 12.8 and c.request_timeout == 5.0
    assert c.offer_query()["geolocation"] == {"in": ["RO"]}


def test_all_datacenters_means_no_filter_and_default_idle_kept():
    @Endpoint(gpu=GpuGroup.ANY, datacenter=DataCenter.all())
    def some_func():
        pass

    assert some_func.config.name == "some-func"
    assert "geolocation" not in some_func.config.offer_query()
    assert some_func.config.idle_timeout == 900
    assert "gpu_name" not in some_func.config.offer_query()


def test_cpu_endpoint_maps_to_cpu_and_ram_filters():
    @Endpoint(name="c", cpu=CpuInstanceType.CPU3G_4_16)
    def f():
        pass

    q = f.config.offer_query()
    assert q["cpu_cores_effective"] == {"gte": 4} and q["cpu_ram"] == {"gte": 16 * 1024}


def test_gpu_and_cpu_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        Endpoint(gpu=GpuGroup.ADA_24, cpu=CpuInstanceType.CPU3G_1_4)


def test_legacy_remote_with_resource_config():
    gpu_cfg = LiveServerless(name="legacy", gpus=[GpuGroup.ADA_24], workersMax=3, idleTimeout=300)

    @remote(resource_config=gpu_cfg, dependencies=["numpy"])
    def f(x):
        return x

    assert f.config.name == "legacy" and f.config.gpus == ["RTX 4090"]
    assert f.config.max_workers == 3 and f.config.idle_timeout == 300
    assert f.config.dependencies == ["numpy"]

    @remote(resource_config=CpuLiveServerless(name="cpu", instanceIds=[CpuInstanceType.CPU3C_2_4]))
    def g():
        pass

    assert g.config.offer_query()["cpu_cores_effective"] == {"gte": 2}


def test_remote_local_returns_plain_function():
    def f(x):
        return x + 1

    assert remote(resource_config=LiveServerless(name="x"), local=True)(f) is f


def test_unsupported_flash_features_fail_clearly():
    with pytest.raises(NotImplementedError, match="load-balanced"):
        remote(resource_config=LiveLoadBalancer(name="lb"))(lambda: None)
    with pytest.raises(NotImplementedError):
        remote(resource_config=LiveServerless(name="x"), method="GET", path="/")
    api = Endpoint(name="api", gpu=GpuGroup.ADA_24)
    with pytest.raises(NotImplementedError, match="load-balanced"):
        api.post("/compute")
    with pytest.raises(NotImplementedError):
        Endpoint(id="abc123")


def test_volume_is_ignored_with_warning():
    from spark import NetworkVolume

    with pytest.warns(UserWarning, match="network volumes"):
        Endpoint(name="v", volume=NetworkVolume(name="models"))
