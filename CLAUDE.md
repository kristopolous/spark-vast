# vastsparks

Vast.ai port of runpod-flash. Package `vastsparks` (src layout), CLI `vastsparks` (`vastsparks.cli:app`). Python >=3.10.

## Layout
- `src/vastsparks/endpoint.py`: `@Endpoint` / `remote` → `RemoteFunction`. Builds a FunctionRequest,
  `backend.ensure()` → `backend.execute()`, and re-provisions once on `StaleResourceError`.
- `src/vastsparks/resources.py`: `EndpointConfig`. `config_hash()` covers hardware only (dependencies are
  excluded), and `offer_query()` builds Vast `/bundles/` JSON.
- `src/vastsparks/backends/{instance,serverless}.py`: the two backends. Serverless is experimental and has
  not been validated live.
- `src/vastsparks/vast.py`: async httpx client for `console.vast.ai/api/v0` and `run.vast.ai/route`.
- `src/vastsparks/worker/server.py`: runs on the GPU box. **Must stay stdlib + cloudpickle only**; it is
  shipped gzip+base64 in the `VASTSPARKS_WORKER_B64` env var, not installed.
- `src/vastsparks/compat.py`: runpod-flash drop-in names (GpuType/GpuGroup/LiveServerless/...) and `flash_to_vastsparks()`
  kwarg mapping. Keep enum names/values identical to Flash; Vast gpu_name tables live here.
- `src/vastsparks/state.py`: `~/.vastsparks/state.json` (file-locked). Holds per-instance tokens.

## Commands
`make dev` · `make test` (no network; spawns the real worker on localhost) · `make lint` · `make format`

## Rules
- Never rent or destroy real Vast resources in tests. Use `FakeVast` in `tests/conftest.py`.
- Record state *before* waiting on a rented instance, so `vastsparks down` can always clean up.
