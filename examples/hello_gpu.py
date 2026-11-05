"""Run with:  uv run python examples/hello_gpu.py   (then `spark down hello-gpu`)"""

import asyncio

from spark import Endpoint


@Endpoint(
    name="hello-gpu",
    gpu=["RTX 3090", "RTX 4090"],
    max_price_per_hour=0.60,
    idle_timeout=600,  # box destroys itself after 10 idle minutes
)
async def hello(n: int):
    import torch  # preinstalled in the default pytorch image

    x = torch.randn(n, n, device="cuda")
    print(f"multiplying {n}x{n} on {torch.cuda.get_device_name(0)}")
    return {"gpu": torch.cuda.get_device_name(0), "trace": float((x @ x).trace())}


if __name__ == "__main__":
    print(asyncio.run(hello(4096)))
