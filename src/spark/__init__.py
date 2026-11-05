"""spark: run Python functions on Vast.ai GPUs with a decorator.

A Vast.ai port of runpod-flash (MIT, Copyright (c) 2026 Runpod).
"""

__version__ = "0.1.0"

from .compat import (
    CPU_DATACENTERS,
    CpuInstanceType,
    CpuLiveLoadBalancer,
    CpuLiveServerless,
    CpuLoadBalancerSlsResource,
    CpuServerlessEndpoint,
    CudaVersion,
    DataCenter,
    GpuGroup,
    GpuType,
    LiveLoadBalancer,
    LiveServerless,
    LoadBalancerSlsResource,
    NetworkVolume,
    PodTemplate,
    ServerlessEndpoint,
    ServerlessScalerType,
    ServerlessType,
)
from .endpoint import Endpoint, RemoteFunction, remote
from .exceptions import (
    ProvisioningError,
    RemoteExecutionError,
    SparkError,
    VastAPIError,
)
from .resources import Backend, EndpointConfig

__all__ = [
    "CPU_DATACENTERS",
    "Backend",
    "CpuInstanceType",
    "CpuLiveLoadBalancer",
    "CpuLiveServerless",
    "CpuLoadBalancerSlsResource",
    "CpuServerlessEndpoint",
    "CudaVersion",
    "DataCenter",
    "Endpoint",
    "EndpointConfig",
    "GpuGroup",
    "GpuType",
    "LiveLoadBalancer",
    "LiveServerless",
    "LoadBalancerSlsResource",
    "NetworkVolume",
    "PodTemplate",
    "ProvisioningError",
    "RemoteExecutionError",
    "RemoteFunction",
    "ServerlessEndpoint",
    "ServerlessScalerType",
    "ServerlessType",
    "SparkError",
    "VastAPIError",
    "remote",
]
