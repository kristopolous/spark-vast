"""runpod-flash compatibility layer.

Lets code written for runpod-flash run on Vast.ai by changing only the import:

    from runpod_flash import Endpoint, GpuGroup   ->   from spark import Endpoint, GpuGroup

Flash's enums and resource-config classes are reproduced here with the same
member names and values, and translated into spark's EndpointConfig (Vast
search filters). Runpod-only knobs that have no Vast meaning are accepted
and ignored; features spark doesn't implement raise a clear error.

Enum names/values adapted from runpod-flash (MIT, Copyright (c) 2026 Runpod).
"""

from __future__ import annotations

import logging
import warnings
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- GPUs


class GpuGroup(Enum):
    ANY = "any"
    ADA_24 = "ADA_24"
    ADA_32_PRO = "ADA_32_PRO"
    ADA_48_PRO = "ADA_48_PRO"
    ADA_80_PRO = "ADA_80_PRO"
    AMPERE_16 = "AMPERE_16"
    AMPERE_24 = "AMPERE_24"
    AMPERE_48 = "AMPERE_48"
    AMPERE_80 = "AMPERE_80"
    HOPPER_141 = "HOPPER_141"
    BLACKWELL_96 = "BLACKWELL_96"
    BLACKWELL_180 = "BLACKWELL_180"

    @classmethod
    def all(cls) -> list[GpuGroup]:
        return [g for g in cls if g != cls.ANY]


class GpuType(Enum):
    ANY = "any"
    NVIDIA_GEFORCE_RTX_4090 = "NVIDIA GeForce RTX 4090"
    NVIDIA_GEFORCE_RTX_5090 = "NVIDIA GeForce RTX 5090"
    NVIDIA_RTX_6000_ADA_GENERATION = "NVIDIA RTX 6000 Ada Generation"
    NVIDIA_RTX_PRO_6000_BLACKWELL_SERVER_EDITION = "NVIDIA RTX PRO 6000 Blackwell Server Edition"
    NVIDIA_RTX_PRO_6000_BLACKWELL_WORKSTATION_EDITION = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"
    NVIDIA_RTX_PRO_6000_BLACKWELL_MAX_Q_WORKSTATION_EDITION = (
        "NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition"
    )
    NVIDIA_H100_80GB_HBM3 = "NVIDIA H100 80GB HBM3"
    NVIDIA_RTX_A4000 = "NVIDIA RTX A4000"
    NVIDIA_RTX_A4500 = "NVIDIA RTX A4500"
    NVIDIA_RTX_4000_ADA_GENERATION = "NVIDIA RTX 4000 Ada Generation"
    NVIDIA_RTX_2000_ADA_GENERATION = "NVIDIA RTX 2000 Ada Generation"
    NVIDIA_RTX_A5000 = "NVIDIA RTX A5000"
    NVIDIA_L4 = "NVIDIA L4"
    NVIDIA_GEFORCE_RTX_3090 = "NVIDIA GeForce RTX 3090"
    NVIDIA_A40 = "NVIDIA A40"
    NVIDIA_RTX_A6000 = "NVIDIA RTX A6000"
    NVIDIA_A100_80GB_PCIe = "NVIDIA A100 80GB PCIe"
    NVIDIA_A100_SXM4_80GB = "NVIDIA A100-SXM4-80GB"
    NVIDIA_H200 = "NVIDIA H200"
    NVIDIA_B200 = "NVIDIA B200"


# Runpod GPU type -> Vast `gpu_name`. Vast names come from its offer listings;
# run `spark gpus` to see what the market currently calls each card.
VAST_GPU_NAMES: dict[GpuType, str] = {
    GpuType.NVIDIA_GEFORCE_RTX_4090: "RTX 4090",
    GpuType.NVIDIA_GEFORCE_RTX_5090: "RTX 5090",
    GpuType.NVIDIA_RTX_6000_ADA_GENERATION: "RTX 6000Ada",
    GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_SERVER_EDITION: "RTX PRO 6000 S",
    GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_WORKSTATION_EDITION: "RTX PRO 6000 WS",
    GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_MAX_Q_WORKSTATION_EDITION: "RTX PRO 6000 Max-Q",
    GpuType.NVIDIA_H100_80GB_HBM3: "H100 SXM",
    GpuType.NVIDIA_RTX_A4000: "RTX A4000",
    GpuType.NVIDIA_RTX_A4500: "RTX A4500",
    GpuType.NVIDIA_RTX_4000_ADA_GENERATION: "RTX 4000Ada",
    GpuType.NVIDIA_RTX_2000_ADA_GENERATION: "RTX 2000Ada",
    GpuType.NVIDIA_RTX_A5000: "RTX A5000",
    GpuType.NVIDIA_L4: "L4",
    GpuType.NVIDIA_GEFORCE_RTX_3090: "RTX 3090",
    GpuType.NVIDIA_A40: "A40",
    GpuType.NVIDIA_RTX_A6000: "RTX A6000",
    GpuType.NVIDIA_A100_80GB_PCIe: "A100 PCIE",
    GpuType.NVIDIA_A100_SXM4_80GB: "A100 SXM4",
    GpuType.NVIDIA_H200: "H200",
    GpuType.NVIDIA_B200: "B200",
}

# Runpod pool -> Vast gpu_names (pools include cards that have no GpuType member).
VAST_GROUP_NAMES: dict[GpuGroup, list[str]] = {
    GpuGroup.ADA_24: ["RTX 4090"],
    GpuGroup.ADA_32_PRO: ["RTX 5090"],
    GpuGroup.ADA_48_PRO: ["RTX 6000Ada", "L40", "L40S"],
    GpuGroup.ADA_80_PRO: ["H100 PCIE", "H100 SXM", "H100 NVL"],
    GpuGroup.AMPERE_16: ["RTX A4000", "RTX A4500", "RTX 4000Ada", "RTX 2000Ada"],
    GpuGroup.AMPERE_24: ["RTX A5000", "L4", "RTX 3090"],
    GpuGroup.AMPERE_48: ["A40", "RTX A6000"],
    GpuGroup.AMPERE_80: ["A100 PCIE", "A100 SXM4"],
    GpuGroup.HOPPER_141: ["H200"],
    GpuGroup.BLACKWELL_96: ["RTX PRO 6000 S", "RTX PRO 6000 WS", "RTX PRO 6000 Max-Q"],
    GpuGroup.BLACKWELL_180: ["B200"],
}


def vast_gpu_names(gpu: Any) -> list[str] | None:
    """Translate Flash/spark GPU specs into Vast gpu_names. None means any GPU."""
    if gpu is None:
        return None
    items = gpu if isinstance(gpu, (list, tuple, set)) else [gpu]
    names: list[str] = []
    for item in items:
        if item in (GpuGroup.ANY, GpuType.ANY, "any"):
            return None
        if isinstance(item, GpuGroup):
            names += VAST_GROUP_NAMES[item]
        elif isinstance(item, GpuType):
            names.append(VAST_GPU_NAMES[item])
        elif isinstance(item, str):
            # Accept Runpod enum values/names as plain strings too.
            for enum in (GpuType, GpuGroup):
                match = enum.__members__.get(item) or next((m for m in enum if m.value == item), None)
                if match is not None:
                    names += vast_gpu_names(match) or []
                    break
            else:
                names.append(item.replace("_", " "))  # native Vast name, e.g. "RTX_4090"
        else:
            raise TypeError(f"unsupported gpu spec: {item!r}")
    return list(dict.fromkeys(names))  # dedupe, keep order


# --------------------------------------------------------------------------- CPU / CUDA / DC


class CpuInstanceType(str, Enum):
    CPU3G_1_4 = "cpu3g-1-4"
    CPU3G_2_8 = "cpu3g-2-8"
    CPU3G_4_16 = "cpu3g-4-16"
    CPU3G_8_32 = "cpu3g-8-32"
    CPU3C_1_2 = "cpu3c-1-2"
    CPU3C_2_4 = "cpu3c-2-4"
    CPU3C_4_8 = "cpu3c-4-8"
    CPU3C_8_16 = "cpu3c-8-16"
    CPU5C_1_2 = "cpu5c-1-2"
    CPU5C_2_4 = "cpu5c-2-4"
    CPU5C_4_8 = "cpu5c-4-8"
    CPU5C_8_16 = "cpu5c-8-16"


def cpu_search(cpu: Any) -> dict:
    """Runpod CPU instance types -> Vast filters on vCPUs and RAM.

    Vast is a GPU marketplace, so a CPU endpoint becomes the cheapest machine
    with at least the requested vCPUs/RAM (it will usually still have a GPU).
    """
    items = cpu if isinstance(cpu, (list, tuple, set)) else [cpu]
    vcpus, ram_gb = [], []
    for item in items:
        value = item.value if isinstance(item, CpuInstanceType) else str(item)
        try:
            _, c, r = value.split("-")
            vcpus.append(int(c))
            ram_gb.append(int(r))
        except ValueError:
            raise ValueError(f"unsupported cpu spec: {item!r}") from None
    return {
        "cpu_cores_effective": {"gte": min(vcpus)},
        "cpu_ram": {"gte": min(ram_gb) * 1024},  # Vast reports MB
    }


class CudaVersion(Enum):
    V11_8 = "11.8"
    V12_0 = "12.0"
    V12_1 = "12.1"
    V12_2 = "12.2"
    V12_3 = "12.3"
    V12_4 = "12.4"
    V12_5 = "12.5"
    V12_6 = "12.6"
    V12_7 = "12.7"
    V12_8 = "12.8"
    V12_9 = "12.9"
    V13_0 = "13.0"


class DataCenter(str, Enum):
    US_CA_2 = "US-CA-2"
    US_IL_1 = "US-IL-1"
    US_KS_2 = "US-KS-2"
    US_MO_1 = "US-MO-1"
    US_MO_2 = "US-MO-2"
    US_NC_2 = "US-NC-2"
    US_NE_1 = "US-NE-1"
    US_WA_1 = "US-WA-1"
    EU_CZ_1 = "EU-CZ-1"
    EU_RO_1 = "EU-RO-1"
    EUR_NO_1 = "EUR-NO-1"

    @classmethod
    def all(cls) -> list[DataCenter]:
        return list(cls)


CPU_DATACENTERS = frozenset(DataCenter)


def datacenter_search(datacenter: Any) -> dict:
    """Runpod datacenters -> Vast geolocation country codes (US-KS-2 -> US, EU-RO-1 -> RO)."""
    items = datacenter if isinstance(datacenter, (list, tuple, set)) else [datacenter]
    if set(items) >= set(DataCenter):
        return {}  # Flash's default "everywhere": no filter
    countries = []
    for item in items:
        parts = (item.value if isinstance(item, DataCenter) else str(item)).split("-")
        countries.append(parts[1] if parts[0] in ("EU", "EUR") and len(parts) > 1 else parts[0])
    return {"geolocation": {"in": sorted(set(countries))}}


class ServerlessScalerType(Enum):
    QUEUE_DELAY = "QUEUE_DELAY"
    REQUEST_COUNT = "REQUEST_COUNT"


class ServerlessType(Enum):
    QB = "QB"
    LB = "LB"


# --------------------------------------------------------------------------- accepted, unused


class _Permissive(BaseModel):
    model_config = ConfigDict(extra="allow")


class NetworkVolume(_Permissive):
    """Accepted for compatibility; Vast has no network volumes in spark yet."""

    name: str | None = None
    size: int | None = 100
    id: str | None = None


class PodTemplate(_Permissive):
    """Accepted for compatibility; use Endpoint(image=..., env=...) instead."""


# --------------------------------------------------------------------------- Endpoint kwargs

FLASH_IGNORED = {
    "accelerate_downloads",
    "flashboot",
    "scaler_type",
    "scaler_value",
    "max_concurrency",
}


def normalize_workers(workers: Any) -> tuple[int, int]:
    if workers is None:
        return (0, 1)
    if isinstance(workers, int):
        lo, hi = 0, workers
    elif isinstance(workers, (tuple, list)) and len(workers) == 2:
        lo, hi = int(workers[0]), int(workers[1])
    else:
        raise ValueError(f"workers must be an int or (min, max) tuple, got {workers!r}")
    if lo < 0 or hi < 0 or lo > hi:
        raise ValueError(f"invalid workers range ({lo}, {hi})")
    return lo, hi


def flash_to_spark(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Map Flash `Endpoint(...)` keyword arguments onto EndpointConfig fields.

    Spark-native keywords (backend, max_price_per_hour, ...) pass through
    unchanged, so the two styles can be mixed.
    """
    kw = dict(kwargs)
    out: dict[str, Any] = {}
    search: dict[str, Any] = dict(kw.pop("search", None) or {})

    gpu, cpu = kw.pop("gpu", None), kw.pop("cpu", None)
    if gpu is not None and cpu is not None:
        raise ValueError("gpu and cpu are mutually exclusive. specify one or neither.")
    if gpu is not None:
        out["gpu"] = vast_gpu_names(gpu)
    if cpu is not None:
        search.update(cpu_search(cpu))

    if "gpu_count" in kw:
        out["num_gpus"] = kw.pop("gpu_count")

    if "workers" in kw:
        lo, hi = normalize_workers(kw.pop("workers"))
        out["cold_workers"], out["max_workers"] = lo, max(hi, 1)

    if kw.get("idle_timeout") is None:
        kw.pop("idle_timeout", None)  # keep spark's default rather than Flash's 60s

    timeout_ms = kw.pop("execution_timeout_ms", 0) or 0
    if timeout_ms > 0:
        out["request_timeout"] = timeout_ms / 1000

    cuda = kw.pop("min_cuda_version", None)
    if cuda is not None:
        out["min_cuda"] = float(cuda.value if isinstance(cuda, CudaVersion) else cuda)

    dc = kw.pop("datacenter", None)
    if dc:
        search.update(datacenter_search(dc))

    if kw.pop("volume", None):
        warnings.warn("spark: network volumes are not supported on Vast yet; ignoring volume=", stacklevel=3)
    if kw.pop("template", None) is not None:
        warnings.warn("spark: PodTemplate is ignored; pass image= and env= instead", stacklevel=3)
    for key in FLASH_IGNORED:
        kw.pop(key, None)

    for key in ("dependencies", "system_dependencies", "env"):
        if kw.get(key) is None:
            kw.pop(key, None)

    if search:
        out["search"] = search
    out.update(kw)  # remaining keys are spark-native (image, backend, max_price_per_hour, ...)
    return out


# --------------------------------------------------------------------------- @remote resource configs


class ServerlessResource(_Permissive):
    """Flash's resource-config models (camelCase fields), for `@remote(resource_config=...)`."""

    name: str
    gpus: list[Any] | None = None
    instanceIds: list[Any] | None = None
    gpuCount: int | None = None
    workersMin: int | None = None
    workersMax: int | None = None
    idleTimeout: int | None = None
    executionTimeoutMs: int | None = None
    minCudaVersion: Any = None
    imageName: str | None = None
    env: dict[str, str] | None = None
    datacenter: Any = None
    networkVolume: Any = None
    template: Any = None

    load_balanced: ClassVar[bool] = False

    def to_endpoint_kwargs(self) -> dict[str, Any]:
        if self.load_balanced:
            raise NotImplementedError(
                f"{type(self).__name__}: load-balanced HTTP endpoints are not supported by spark yet"
            )
        kw: dict[str, Any] = {"env": self.env, "datacenter": self.datacenter}
        if self.instanceIds:
            kw["cpu"] = self.instanceIds
        elif self.gpus:
            kw["gpu"] = self.gpus
        if self.gpuCount:
            kw["gpu_count"] = self.gpuCount
        if self.workersMin is not None or self.workersMax is not None:
            kw["workers"] = (self.workersMin or 0, self.workersMax or 1)
        if self.idleTimeout is not None:
            kw["idle_timeout"] = self.idleTimeout
        if self.executionTimeoutMs:
            kw["execution_timeout_ms"] = self.executionTimeoutMs
        if self.minCudaVersion is not None:
            kw["min_cuda_version"] = self.minCudaVersion
        if self.imageName:
            kw["image"] = self.imageName
        if self.networkVolume is not None:
            kw["volume"] = self.networkVolume
        return {k: v for k, v in kw.items() if v is not None}


class ServerlessEndpoint(ServerlessResource):
    pass


class LiveServerless(ServerlessEndpoint):
    pass


class CpuServerlessEndpoint(ServerlessResource):
    pass


class CpuLiveServerless(CpuServerlessEndpoint):
    pass


class LoadBalancerSlsResource(ServerlessResource):
    load_balanced: ClassVar[bool] = True


class CpuLoadBalancerSlsResource(LoadBalancerSlsResource):
    pass


class LiveLoadBalancer(LoadBalancerSlsResource):
    pass


class CpuLiveLoadBalancer(LoadBalancerSlsResource):
    pass
