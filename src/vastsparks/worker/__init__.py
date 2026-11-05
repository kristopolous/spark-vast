"""Bootstrap material for vastsparks workers on Vast.ai.

The worker code is shipped gzip+base64 inside an environment variable and
unpacked by a short onstart script, so nothing needs to be published to a
registry or a public git repo.
"""

import base64
import gzip
from importlib import resources

WORKER_DIR = "/opt/vastsparks"
SERVERLESS_PORT = 18000
SERVERLESS_LOG = "/var/log/vastsparks/worker.log"


def _packed(filename: str) -> str:
    raw = resources.files(__package__).joinpath(filename).read_bytes()
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")


def packed_server() -> str:
    return _packed("server.py")


def packed_pyworker() -> str:
    return _packed("pyworker.py")


def instance_onstart() -> str:
    """Onstart for the on-demand backend: run the worker on VASTSPARKS_PORT."""
    return "\n".join(
        [
            "#!/bin/bash",
            "env | grep -E '^(VASTSPARKS_|CONTAINER_|VAST_)' | grep -v '_B64=' >> /etc/environment",
            f"mkdir -p {WORKER_DIR} && cd {WORKER_DIR}",
            'echo "$VASTSPARKS_WORKER_B64" | base64 -d | gunzip > server.py',
            "python3 -m pip install -q --no-input cloudpickle >> install.log 2>&1",
            "nohup python3 server.py >> worker.log 2>&1 &",
        ]
    )


def serverless_onstart(pyworker_pip: str) -> str:
    """Onstart for the serverless backend: vastsparks worker + Vast PyWorker."""
    return "\n".join(
        [
            "#!/bin/bash",
            "env | grep -E '^(VASTSPARKS_|CONTAINER_|VAST_)' | grep -v '_B64=' >> /etc/environment",
            f"mkdir -p {WORKER_DIR} /var/log/vastsparks && cd {WORKER_DIR}",
            'echo "$VASTSPARKS_WORKER_B64" | base64 -d | gunzip > server.py',
            'echo "$VASTSPARKS_PYWORKER_B64" | base64 -d | gunzip > pyworker.py',
            f"python3 -m pip install -q --no-input cloudpickle {pyworker_pip} >> install.log 2>&1",
            (
                f"VASTSPARKS_MODE=serverless VASTSPARKS_PORT={SERVERLESS_PORT} VASTSPARKS_LOG_FILE={SERVERLESS_LOG} "
                "nohup python3 server.py >> worker.log 2>&1 &"
            ),
            (
                f"VASTSPARKS_PORT={SERVERLESS_PORT} VASTSPARKS_LOG_FILE={SERVERLESS_LOG} "
                "nohup python3 pyworker.py >> pyworker.log 2>&1 &"
            ),
        ]
    )
