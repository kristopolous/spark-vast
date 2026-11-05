"""Vast Serverless PyWorker that fronts the spark worker.

Runs on each serverless worker instance next to `server.py` (started in
SPARK_MODE=serverless on 127.0.0.1:18000). The PyWorker validates Vast's
routing signatures, forwards `/execute` payloads to the spark worker, and
reports load to the autoscaler. Readiness is detected from the spark
worker's log line.

Based on https://docs.vast.ai/guides/serverless/creating-new-pyworkers
"""

import os

from vastai import (  # provided by the Vast serverless SDK
    BenchmarkConfig,
    HandlerConfig,
    LogActionConfig,
    Worker,
    WorkerConfig,
)

PORT = int(os.environ.get("SPARK_PORT", "18000"))
LOG_FILE = os.environ.get("SPARK_LOG_FILE", "/var/log/spark/worker.log")

# A trivial request the autoscaler can time while the worker warms up.
PING = {
    "function_name": "_spark_ping",
    "function_code": "def _spark_ping():\n    return 1\n",
}

worker_config = WorkerConfig(
    model_server_url="http://127.0.0.1",
    model_server_port=PORT,
    model_log_file=LOG_FILE,
    handlers=[
        HandlerConfig(
            route="/execute",
            allow_parallel_requests=False,
            max_queue_time=float(os.environ.get("SPARK_MAX_QUEUE_TIME", "600")),
            workload_calculator=lambda payload: 100.0,
            benchmark_config=BenchmarkConfig(dataset=[PING], runs=3, concurrency=1),
        ),
    ],
    log_action_config=LogActionConfig(
        on_load=["[spark-worker] SPARK WORKER READY"],
        on_error=["[spark-worker] SPARK WORKER FATAL", "Traceback (most recent call last):"],
        on_info=["[spark-worker]"],
    ),
)

if __name__ == "__main__":
    Worker(worker_config).run()
