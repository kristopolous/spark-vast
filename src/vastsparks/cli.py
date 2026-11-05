"""`vastsparks` command line."""

import asyncio
import logging
import time

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, state
from .backends import get_backend
from .config import save_api_key
from .exceptions import VastsparksError
from .resources import EndpointConfig
from .vast import VastClient

app = typer.Typer(help="Run Python functions on Vast.ai GPUs.", no_args_is_help=True)
console = Console()


def _run(coro):
    try:
        return asyncio.run(coro)
    except VastsparksError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(1) from None


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command()
def version() -> None:
    """Print the vastsparks version."""
    console.print(__version__)


@app.command()
def login(api_key: str = typer.Option(..., prompt="Vast.ai API key", hide_input=True)) -> None:
    """Save a Vast.ai API key (https://cloud.vast.ai/manage-keys/)."""

    async def check():
        async with VastClient(api_key=api_key) as vast:
            await vast.list_instances()

    _run(check())
    path = save_api_key(api_key)
    console.print(f"[green]Key verified and saved to {path}[/green]")


@app.command()
def offers(
    gpu: list[str] | None = typer.Option(None, "--gpu", "-g", help='e.g. "RTX 4090" (repeatable)'),
    num_gpus: int = typer.Option(1, "--num-gpus", "-n"),
    max_price: float | None = typer.Option(None, "--max-price", help="USD/hr"),
    disk: float = typer.Option(40, "--disk"),
    limit: int = typer.Option(10, "--limit"),
) -> None:
    """Show the cheapest offers vastsparks would rent for these filters."""
    cfg = EndpointConfig(
        name="offers", gpu=gpu or None, num_gpus=num_gpus, max_price_per_hour=max_price, disk_gb=disk
    )

    async def go():
        async with VastClient() as vast:
            return await vast.search_offers({**cfg.offer_query(), "limit": limit})

    rows = _run(go())
    table = Table("offer id", "gpu", "#", "$/hr", "vram GB", "cuda", "reliability", "location")
    for o in rows[:limit]:
        table.add_row(
            str(o.get("id")),
            str(o.get("gpu_name")),
            str(o.get("num_gpus")),
            f"{o.get('dph_total', 0):.3f}",
            f"{(o.get('gpu_ram') or 0) / 1024:.0f}",
            str(o.get("cuda_max_good")),
            f"{o.get('reliability2', 0):.3f}",
            str(o.get("geolocation")),
        )
    console.print(table if rows else "[yellow]No matching offers.[/yellow]")


@app.command()
def gpus() -> None:
    """List GPU names on the Vast market and which Runpod GpuType/GpuGroup maps to each."""
    from .compat import VAST_GPU_NAMES, VAST_GROUP_NAMES

    async def go():
        async with VastClient() as vast:
            q = {"rentable": {"eq": True}, "rented": {"eq": False}, "limit": 5000, "type": "on-demand"}
            return await vast.search_offers(q)

    stats: dict[str, list[float]] = {}
    for o in _run(go()):
        stats.setdefault(str(o.get("gpu_name")), []).append(o.get("dph_total") or 0)
    mapped = set(VAST_GPU_NAMES.values()) | {n for ns in VAST_GROUP_NAMES.values() for n in ns}
    table = Table("vast gpu_name", "offers", "from $/hr", "runpod-flash names mapped here")
    for name, prices in sorted(stats.items(), key=lambda kv: -len(kv[1])):
        flash = [t.name for t, n in VAST_GPU_NAMES.items() if n == name]
        flash += [g.name for g, ns in VAST_GROUP_NAMES.items() if name in ns]
        table.add_row(name, str(len(prices)), f"{min(prices):.3f}", ", ".join(flash) or "-")
    console.print(table)
    missing = sorted(mapped - set(stats))
    if missing:
        console.print(f"[yellow]Mapped names with no current offers: {', '.join(missing)}[/yellow]")


@app.command("ls")
def list_endpoints() -> None:
    """List endpoints vastsparks has provisioned (from ~/.vastsparks/state.json)."""
    entries = state.all_entries()
    if not entries:
        console.print("Nothing provisioned.")
        return

    async def statuses():
        out = {}
        async with VastClient() as vast:
            for name, e in entries.items():
                if e.get("backend") == "instance":
                    inst = await vast.show_instance(e["instance_id"])
                    out[name] = (inst or {}).get("actual_status") or "gone"
                else:
                    out[name] = "endpoint"
        return out

    live = _run(statuses())
    table = Table("name", "backend", "vast id", "status", "gpu", "$/hr", "age")
    for name, e in sorted(entries.items()):
        vid = e.get("instance_id") or e.get("endpoint_id")
        age = time.time() - e.get("created_at", time.time())
        table.add_row(
            name,
            e.get("backend", "?"),
            str(vid),
            live.get(name, "?"),
            str(e.get("gpu") or "-"),
            f"{e['dph_total']:.3f}" if e.get("dph_total") else "-",
            f"{age / 3600:.1f}h",
        )
    console.print(table)


@app.command()
def down(
    names: list[str] | None = typer.Argument(None, help="endpoint names"),
    all_: bool = typer.Option(False, "--all", help="tear down everything vastsparks provisioned"),
) -> None:
    """Destroy the Vast instances/endpoints behind endpoints (stops billing)."""
    entries = state.all_entries()
    targets = list(entries) if all_ else (names or [])
    if not targets:
        console.print("Give endpoint names or --all.")
        raise typer.Exit(1)

    async def go():
        async with VastClient() as vast:
            for name in targets:
                entry = entries.get(name)
                if not entry:
                    console.print(f"[yellow]{name}: not found[/yellow]")
                    continue
                await get_backend(entry["backend"]).teardown(entry, vast)
                state.remove(name)
                console.print(f"[green]{name}: destroyed[/green]")

    _run(go())


@app.command()
def orphans(destroy: bool = typer.Option(False, "--destroy")) -> None:
    """Find instances labelled vastsparks-* on your account that vastsparks lost track of."""
    known = {e.get("instance_id") for e in state.all_entries().values()}

    async def go():
        async with VastClient() as vast:
            found = [
                i
                for i in await vast.list_instances()
                if str(i.get("label") or "").startswith("vastsparks-") and i.get("id") not in known
            ]
            for i in found:
                console.print(
                    f"{i['id']}  {i.get('label')}  {i.get('actual_status')}  ${i.get('dph_total', 0):.3f}/hr"
                )
                if destroy:
                    await vast.destroy_instance(i["id"])
                    console.print(f"  [green]destroyed {i['id']}[/green]")
            if not found:
                console.print("No orphaned vastsparks instances.")

    _run(go())


if __name__ == "__main__":
    app()
