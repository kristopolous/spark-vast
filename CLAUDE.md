# spark-vast

Vast.ai port of runpod-flash. Package `spark` (src layout), CLI `spark` (`spark.cli:app`). Python >=3.10.

## Layout
- `src/spark/endpoint.py`: `@Endpoint` / `remote` → `RemoteFunction`. Builds a FunctionRequest,
  `backend.ensure()` → `backend.execute()`, and re-provisions once on `StaleResourceError`.
- `src/spark/resources.py`: `EndpointConfig`. `config_hash()` covers hardware only (dependencies are
  excluded), and `offer_query()` builds Vast `/bundles/` JSON.
- `src/spark/backends/{instance,serverless}.py`: the two backends. Serverless is experimental and has
  not been validated live.
- `src/spark/vast.py`: async httpx client for `console.vast.ai/api/v0` and `run.vast.ai/route`.
- `src/spark/worker/server.py`: runs on the GPU box. **Must stay stdlib + cloudpickle only**; it is
  shipped gzip+base64 in the `SPARK_WORKER_B64` env var, not installed.
- `src/spark/state.py`: `~/.spark/state.json` (file-locked). Holds per-instance tokens.

## Commands
`make dev` · `make test` (no network; spawns the real worker on localhost) · `make lint` · `make format`

## Rules
- Never rent or destroy real Vast resources in tests. Use `FakeVast` in `tests/conftest.py`.
- Record state *before* waiting on a rented instance, so `spark down` can always clean up.
