"""Vastsparks worker: executes FunctionRequests on a Vast.ai instance.

Self-contained on purpose: stdlib + cloudpickle only, so it can be shipped
inside an instance's onstart script and started without installing vastsparks.

Environment:
  VASTSPARKS_MODE          "instance" (default) or "serverless"
  VASTSPARKS_PORT          listen port (default 8000)
  VASTSPARKS_HOST          bind address (default 0.0.0.0; 127.0.0.1 in serverless mode)
  VASTSPARKS_TOKEN         bearer token required on /execute (instance mode)
  VASTSPARKS_IDLE_TIMEOUT  seconds without requests before the instance destroys
                      itself (instance mode; 0 disables)
  VASTSPARKS_LOG_FILE      also append log lines here (serverless readiness detection)
  CONTAINER_ID / CONTAINER_API_KEY   injected by Vast; used for self-teardown
"""

import asyncio
import base64
import contextlib
import hmac
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cloudpickle

READY_LINE = "VASTSPARKS WORKER READY"
ERROR_LINE = "VASTSPARKS WORKER FATAL"

MODE = os.environ.get("VASTSPARKS_MODE", "instance")
PORT = int(os.environ.get("VASTSPARKS_PORT", "8000"))
HOST = os.environ.get("VASTSPARKS_HOST", "127.0.0.1" if MODE == "serverless" else "0.0.0.0")
TOKEN = os.environ.get("VASTSPARKS_TOKEN", "")
IDLE_TIMEOUT = int(os.environ.get("VASTSPARKS_IDLE_TIMEOUT", "0"))
LOG_FILE = os.environ.get("VASTSPARKS_LOG_FILE")
MAX_BODY = 512 * 1024 * 1024

_exec_lock = threading.Lock()
_installed: set[str] = set()
_last_activity = time.monotonic()
_started = time.time()


def log(msg: str) -> None:
    line = f"[vastsparks-worker] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")


def _gpu_name() -> str | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None


GPU = _gpu_name()


def _install(pip_specs: list[str], apt_pkgs: list[str], out: io.StringIO) -> None:
    apt_new = [p for p in apt_pkgs if f"apt:{p}" not in _installed]
    if apt_new:
        for cmd in (["apt-get", "update", "-qq"], ["apt-get", "install", "-y", "-qq", *apt_new]):
            r = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{' '.join(cmd)} failed:\n{r.stderr[-4000:]}")
        _installed.update(f"apt:{p}" for p in apt_new)

    pip_new = [p for p in pip_specs if f"pip:{p}" not in _installed]
    if pip_new:
        out.write(f"[vastsparks] pip install {' '.join(pip_new)}\n")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--no-input", *pip_new],
            check=False,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"pip install failed:\n{r.stderr[-4000:]}")
        _installed.update(f"pip:{p}" for p in pip_new)


def _write_modules(modules: dict) -> None:
    if not modules:
        return
    root = Path(tempfile.mkdtemp(prefix="vastsparks_mods_"))
    for rel, text in modules.items():
        path = (root / rel).resolve()
        if root.resolve() not in path.parents:
            raise ValueError(f"refusing module path outside bundle: {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    sys.path.insert(0, str(root))
    for name in list(sys.modules):  # make re-shipped local modules reload
        mod = sys.modules.get(name)
        if getattr(mod, "__file__", None) and str(mod.__file__).startswith(
            tempfile.gettempdir() + "/vastsparks_mods_"
        ):
            del sys.modules[name]


def execute(req: dict) -> dict:
    out = io.StringIO()
    t0 = time.time()
    try:
        _install(req.get("dependencies") or [], req.get("system_dependencies") or [], out)
        _write_modules(req.get("modules") or {})

        ns: dict = {"__name__": "__vastsparks_main__"}
        exec(compile(req["function_code"], f"<vastsparks:{req['function_name']}>", "exec"), ns)
        fn = ns[req["function_name"]]
        args = [cloudpickle.loads(base64.b64decode(a)) for a in req.get("args") or []]
        kwargs = {k: cloudpickle.loads(base64.b64decode(v)) for k, v in (req.get("kwargs") or {}).items()}

        with contextlib.redirect_stdout(out):
            result = fn(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)

        return {
            "success": True,
            "result": base64.b64encode(cloudpickle.dumps(result)).decode("ascii"),
            "stdout": out.getvalue(),
            "worker": _meta(t0),
        }
    except Exception:
        return {
            "success": False,
            "error": traceback.format_exc(),
            "stdout": out.getvalue(),
            "worker": _meta(t0),
        }


def _meta(t0: float) -> dict:
    return {
        "python": sys.version.split()[0],
        "gpu": GPU,
        "seconds": round(time.time() - t0, 3),
        "instance_id": os.environ.get("CONTAINER_ID"),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "vastsparks-worker"

    def log_message(self, fmt, *args):  # quieter default logging
        log(f"{self.address_string()} {fmt % args}")

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        if MODE == "serverless":
            return True  # PyWorker in front of us validates Vast signatures
        got = self.headers.get("Authorization", "")
        return bool(TOKEN) and hmac.compare_digest(got, f"Bearer {TOKEN}")

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "gpu": GPU, "uptime": round(time.time() - _started)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        global _last_activity
        if self.path not in ("/execute", "/execute/"):
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            return self._send(413, {"error": "bad body size"})
        try:
            req = json.loads(self.rfile.read(length))
        except ValueError:
            return self._send(400, {"error": "invalid json"})

        _last_activity = time.monotonic()
        with _exec_lock:  # one call at a time: shared GPU, shared stdout
            resp = execute(req)
        _last_activity = time.monotonic()
        self._send(200, resp)


def _self_destroy() -> None:
    cid, key = os.environ.get("CONTAINER_ID"), os.environ.get("CONTAINER_API_KEY")
    if not (cid and key):
        log("idle timeout reached but CONTAINER_ID/CONTAINER_API_KEY not set; staying up")
        return
    api = os.environ.get("VAST_API_URL", "https://console.vast.ai/api/v0")
    req = urllib.request.Request(
        f"{api}/instances/{cid}/",
        method="DELETE",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "vastsparks-worker"},
    )
    try:
        urllib.request.urlopen(req, timeout=30)
        log(f"idle for {IDLE_TIMEOUT}s; destroyed instance {cid}")
    except Exception as e:
        log(f"self-destroy failed: {e}")


def _idle_watchdog() -> None:
    while True:
        time.sleep(30)
        if _exec_lock.locked():
            continue
        if time.monotonic() - _last_activity > IDLE_TIMEOUT:
            _self_destroy()
            return


def main() -> None:
    if MODE == "instance" and not TOKEN:
        log(f"{ERROR_LINE}: VASTSPARKS_TOKEN is required in instance mode")
        sys.exit(1)
    if MODE == "instance" and IDLE_TIMEOUT > 0:
        threading.Thread(target=_idle_watchdog, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"{READY_LINE} on {HOST}:{PORT} mode={MODE} gpu={GPU}")
    server.serve_forever()


if __name__ == "__main__":
    main()
