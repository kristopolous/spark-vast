"""Bootstrap material for spark workers on Vast.ai.

The worker code is shipped gzip+base64 inside an environment variable and
unpacked by a short onstart script, so nothing needs to be published to a
registry or a public git repo.
"""

import base64
import gzip
from importlib import resources

WORKER_DIR = "/opt/spark"
SERVERLESS_PORT = 18000
SERVERLESS_LOG = "/var/log/spark/worker.log"


def _packed(filename: str) -> str:
    raw = resources.files(__package__).joinpath(filename).read_bytes()
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")


def packed_server() -> str:
    return _packed("server.py")


def packed_pyworker() -> str:
    return _packed("pyworker.py")


def instance_onstart() -> str:
    """Onstart for the on-demand backend: run the worker on SPARK_PORT."""
    return "\n".join(
        [
            "#!/bin/bash",
            "env | grep -E '^(SPARK_|CONTAINER_|VAST_)' | grep -v '_B64=' >> /etc/environment",
            f"mkdir -p {WORKER_DIR} && cd {WORKER_DIR}",
            'echo "$SPARK_WORKER_B64" | base64 -d | gunzip > server.py',
            "python3 -m pip install -q --no-input cloudpickle >> install.log 2>&1",
            "nohup python3 server.py >> worker.log 2>&1 &",
        ]
    )


def serverless_onstart(pyworker_pip: str) -> str:
    """Onstart for the serverless backend: spark worker + Vast PyWorker."""
    return "\n".join(
        [
            "#!/bin/bash",
            "env | grep -E '^(SPARK_|CONTAINER_|VAST_)' | grep -v '_B64=' >> /etc/environment",
            f"mkdir -p {WORKER_DIR} /var/log/spark && cd {WORKER_DIR}",
            'echo "$SPARK_WORKER_B64" | base64 -d | gunzip > server.py',
            'echo "$SPARK_PYWORKER_B64" | base64 -d | gunzip > pyworker.py',
            f"python3 -m pip install -q --no-input cloudpickle {pyworker_pip} >> install.log 2>&1",
            (
                f"SPARK_MODE=serverless SPARK_PORT={SERVERLESS_PORT} SPARK_LOG_FILE={SERVERLESS_LOG} "
                "nohup python3 server.py >> worker.log 2>&1 &"
            ),
            (
                f"SPARK_PORT={SERVERLESS_PORT} SPARK_LOG_FILE={SERVERLESS_LOG} "
                "nohup python3 pyworker.py >> pyworker.log 2>&1 &"
            ),
        ]
    )
