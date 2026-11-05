"""Endpoint configuration: what hardware to rent and how."""

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

DEFAULT_IMAGE = "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime"
DEFAULT_MIN_CUDA = 12.4  # what DEFAULT_IMAGE needs from the host driver


class Backend(str, Enum):
    INSTANCE = "instance"  # on-demand instance per endpoint; cheapest, you control lifetime
    SERVERLESS = "serverless"  # Vast Serverless endpoint + workergroup; autoscaled


class EndpointConfig(BaseModel):
    name: str
    backend: Backend = Backend.INSTANCE

    # hardware
    gpu: str | list[str] | None = Field(
        default=None, description='Vast gpu_name, e.g. "RTX 4090" or ["RTX 4090", "RTX 3090"]'
    )
    num_gpus: int = 1
    min_gpu_ram_gb: float | None = None
    disk_gb: float = 40
    max_price_per_hour: float | None = Field(default=None, description="USD/hr cap (dph_total)")
    min_cuda: float | None = None
    min_reliability: float = 0.95
    search: dict[str, Any] = Field(
        default_factory=dict,
        description='Extra raw Vast search filters, e.g. {"geolocation": {"in": ["US", "CA"]}}',
    )

    # software
    image: str = DEFAULT_IMAGE
    env: dict[str, str] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    system_dependencies: list[str] = Field(default_factory=list)

    # lifecycle
    idle_timeout: int = Field(
        default=900, description="instance backend: seconds idle before the box destroys itself (0 = never)"
    )
    provision_timeout: int = 1200
    request_timeout: float = 3600

    # serverless backend
    max_workers: int = 3
    cold_workers: int = 1
    min_load: float = 1
    target_util: float = 0.9
    pyworker_pip: str = "vastai-sdk"

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("name must be non-empty and use only letters, digits, '-' and '_'")
        return v

    @property
    def gpus(self) -> list[str]:
        if self.gpu is None:
            return []
        names = [self.gpu] if isinstance(self.gpu, str) else list(self.gpu)
        return [g.replace("_", " ") for g in names]

    def config_hash(self) -> str:
        """Hash of everything that requires new hardware when it changes.

        Dependencies are installed per call, so they are not part of it.
        """
        infra = self.model_dump(
            mode="json",
            exclude={"dependencies", "system_dependencies", "request_timeout", "provision_timeout"},
        )
        return hashlib.sha256(json.dumps(infra, sort_keys=True).encode()).hexdigest()[:16]

    def offer_query(self) -> dict:
        """Vast /bundles/ JSON search query, cheapest first."""
        q: dict[str, Any] = {
            "rentable": {"eq": True},
            "rented": {"eq": False},
            "verified": {"eq": True},
            "num_gpus": {"eq": self.num_gpus},
            "disk_space": {"gte": self.disk_gb},
            "reliability2": {"gte": self.min_reliability},
            "direct_port_count": {"gte": 1},
            "order": [["dph_total", "asc"]],
            "type": "on-demand",
            "limit": 20,
        }
        gpus = self.gpus
        if len(gpus) == 1:
            q["gpu_name"] = {"eq": gpus[0]}
        elif gpus:
            q["gpu_name"] = {"in": gpus}
        if self.min_gpu_ram_gb:
            q["gpu_ram"] = {"gte": self.min_gpu_ram_gb * 1024}  # Vast reports MB
        if self.max_price_per_hour is not None:
            q["dph_total"] = {"lte": self.max_price_per_hour}
        cuda = self.min_cuda or (DEFAULT_MIN_CUDA if self.image == DEFAULT_IMAGE else None)
        if cuda:
            q["cuda_max_good"] = {"gte": cuda}
        q.update(self.search)
        return q

    def search_params_string(self) -> str:
        """Same filters in the CLI string syntax that workergroups take."""
        parts = [
            "verified=true",
            "rentable=true",
            "rented=false",
            f"num_gpus={self.num_gpus}",
            f"disk_space>={self.disk_gb}",
            f"reliability>={self.min_reliability}",
            "direct_port_count>=1",
        ]
        gpus = self.gpus
        if len(gpus) == 1:
            parts.append(f"gpu_name={gpus[0].replace(' ', '_')}")
        elif gpus:
            parts.append("gpu_name in [" + ",".join(g.replace(" ", "_") for g in gpus) + "]")
        if self.min_gpu_ram_gb:
            parts.append(f"gpu_ram>={self.min_gpu_ram_gb}")
        if self.max_price_per_hour is not None:
            parts.append(f"dph_total<={self.max_price_per_hour}")
        cuda = self.min_cuda or (DEFAULT_MIN_CUDA if self.image == DEFAULT_IMAGE else None)
        if cuda:
            parts.append(f"cuda_vers>={cuda}")
        return " ".join(parts)
