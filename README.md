# spark

Run a Python function on a [Vast.ai](https://vast.ai) GPU by decorating it. Spark is a Vast.ai port of
[runpod-flash](https://github.com/runpod/flash) (MIT): "a spark is kinda like a flash."

```python
import asyncio
from spark import Endpoint

@Endpoint(name="hello-gpu", gpu="RTX 4090", dependencies=["transformers"])
async def hello():
    import torch
    return torch.cuda.get_device_name(0)

print(asyncio.run(hello()))   # rents a 4090, runs the function there, returns the result
```

The first call rents the cheapest matching machine and starts the spark worker on it. Later calls reuse
that machine. Arguments and return values are pickled with cloudpickle. Remote `print` output is shown
locally, and remote exceptions are raised locally with their traceback. Any local `.py` modules the
function imports are shipped with it.

## Coming from runpod-flash

Spark is a drop-in replacement for runpod-flash. Change the import and your endpoints run on Vast.ai:

```diff
- from runpod_flash import Endpoint, GpuGroup, GpuType
+ from spark import Endpoint, GpuGroup, GpuType

  @Endpoint(name="worker", gpu=GpuGroup.ADA_24, workers=(0, 3), dependencies=["torch"])
  async def process(data: dict) -> dict: ...
```

All 20 of Flash's public names import from `spark`: `remote`, `Endpoint`, `LiveServerless`,
`CpuLiveServerless`, `ServerlessEndpoint`, `GpuGroup`, `GpuType`, `CpuInstanceType`, `CudaVersion`,
`DataCenter`, `NetworkVolume`, `PodTemplate`, and the rest. The legacy
`@remote(resource_config=LiveServerless(...), dependencies=[...])` form and `remote(..., local=True)`
work too. This is how each Flash setting maps to Vast:

| Flash | On Vast |
|---|---|
| `gpu=GpuType.NVIDIA_GEFORCE_RTX_4090` | `gpu_name = "RTX 4090"` |
| `gpu=GpuGroup.AMPERE_24` | any of `RTX A5000`, `L4`, `RTX 3090` (every pool is mapped; see `spark/compat.py`) |
| `gpu=GpuGroup.ANY` / omitted | no GPU filter, so the cheapest matching box |
| `cpu=CpuInstanceType.CPU3G_4_16` | cheapest box with ≥4 vCPU and ≥16 GB RAM (Vast is a GPU market, so it usually comes with a GPU) |
| `gpu_count=2` | `num_gpus = 2` |
| `workers=(min, max)` | serverless `cold_workers`/`max_workers`. The instance backend always uses one box |
| `idle_timeout=N` | the instance destroys itself after N idle seconds (default 900 instead of Flash's 60, to avoid re-renting on every call) |
| `execution_timeout_ms` | client request timeout |
| `min_cuda_version=CudaVersion.V12_8` | `cuda_max_good >= 12.8` |
| `datacenter=DataCenter.US_KS_2` | `geolocation in [US]` (country only) |
| `env`, `dependencies`, `system_dependencies` | same |
| `image="..."` | base image for the spark worker (any image with `python3` and `pip`) |
| `flashboot`, `scaler_type`, `scaler_value`, `accelerate_downloads`, `max_concurrency` | accepted and ignored |
| `volume=NetworkVolume(...)`, `template=PodTemplate(...)` | accepted, warned about, and ignored |

Not supported yet, and these raise `NotImplementedError` with a clear message: load-balanced routes
(`api.get/.post`, `LiveLoadBalancer`, `@remote(method=, path=)`), client mode (`Endpoint(id=...)`,
`.run/.runsync/.status`), class endpoints, and the `flash` CLI's `build/deploy/app/env` commands.

Spark-native options can be mixed in, for example
`@Endpoint(gpu=GpuGroup.ADA_24, max_price_per_hour=0.4, backend="serverless")`.

`spark gpus` lists the GPU names currently on the Vast market and which Flash names map to each, so you
can check the mapping against live supply.

## Setup

```bash
uv sync --all-groups
uv run spark login            # or export VAST_API_KEY=...; ~/.config/vastai/vast_api_key also works
uv run spark offers -g "RTX 4090" --max-price 0.5
uv run python examples/hello_gpu.py
```

## Two backends

| | `backend="instance"` (default) | `backend="serverless"` |
|---|---|---|
| What it rents | One on-demand instance per endpoint | A Vast Serverless endpoint + workergroup |
| Best for | Cost control, dev, batch jobs | Bursty or multi-user traffic, enterprise |
| Billing | Only while the box exists. It destroys itself after `idle_timeout` seconds idle | Whatever cold/hot workers the autoscaler keeps |
| Request path | client → `http://ip:port/execute` (per-instance bearer token) | client → `run.vast.ai/route` → PyWorker → spark worker |
| Status | Tested end to end against a local worker | **Experimental**: built from the docs, not yet run live |

```python
@Endpoint(name="embed", backend="serverless", gpu="RTX 4090", max_workers=5, cold_workers=1)
async def embed(texts): ...
```

## Endpoint options

`gpu` (a name or a list, e.g. `"RTX 4090"`), `num_gpus`, `min_gpu_ram_gb`, `max_price_per_hour`,
`disk_gb`, `min_cuda`, `min_reliability`, and `search` (raw Vast filters such as
`{"geolocation": {"in": ["US"]}}`) choose the hardware.

`image` (default `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`), `env`, `dependencies` (pip), and
`system_dependencies` (apt) set up the software. Dependencies are installed on first use and cached on
the worker. Changing hardware fields replaces the machine; changing dependencies does not.

`idle_timeout`, `provision_timeout`, and `request_timeout` control the lifecycle.

`fn.local(...)` runs the original function in-process, and `fn.sync(...)` is a blocking call.

## CLI

```
spark login            save + verify API key
spark offers           cheapest offers for given filters
spark gpus             Vast GPU names on the market + which Flash GpuType/GpuGroup maps to each
spark ls               what spark has provisioned, with live status and $/hr
spark down NAME|--all  destroy instances/endpoints (stops billing)
spark orphans          find spark-* instances spark lost track of (--destroy to remove)
```

State is kept in `~/.spark/state.json`.

## How it works

- `src/spark/endpoint.py`: the decorator. It extracts the function source, serializes the arguments,
  provisions the endpoint, executes the call, and re-provisions once if the machine has disappeared.
- `src/spark/backends/`: `instance.py` and `serverless.py` against `src/spark/vast.py` (the REST client).
- `src/spark/worker/server.py`: a self-contained worker that needs only the standard library and
  cloudpickle. It is shipped gzip+base64 in an env var and unpacked by a short onstart script, so no
  image build or registry is needed. `worker/pyworker.py` is Vast's PyWorker config for serverless.

## Caveats

- Keep your local Python version close to the image's (3.11 for the default image). cloudpickle
  across versions works for plain data but can break for functions and classes passed as arguments.
- Instance mode uses plain HTTP to the box with a random bearer token. That's fine for a hackathon,
  but don't send secrets as arguments.
- Not ported from Flash: class endpoints, `flash build/deploy` artifacts, apps/environments,
  load-balanced HTTP routes, and cross-endpoint calls.
- The Vast GPU names in the Flash mapping come from Vast's listings and haven't been checked against
  the live market from here. `spark gpus` shows any mapped name that currently has no offers.

## License

MIT. See `LICENSE` (original Runpod copyright retained) and `NOTICE`.
