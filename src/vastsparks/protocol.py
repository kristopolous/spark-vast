"""Wire protocol between the vastsparks client and the vastsparks worker.

Field names match runpod-flash's FunctionRequest/FunctionResponse so the
shape stays familiar, trimmed to what the vastsparks worker implements
(plain function execution).
"""

from typing import Any

from pydantic import BaseModel, Field


class FunctionRequest(BaseModel):
    function_name: str
    function_code: str
    args: list[str] = Field(default_factory=list, description="base64 cloudpickle")
    kwargs: dict[str, str] = Field(default_factory=dict, description="base64 cloudpickle")
    dependencies: list[str] = Field(default_factory=list, description="pip specs")
    system_dependencies: list[str] = Field(default_factory=list, description="apt packages")
    modules: dict[str, str] = Field(
        default_factory=dict,
        description="Local module sources keyed by POSIX relative path; written to a "
        "directory on sys.path before the function code is exec'd.",
    )


class FunctionResponse(BaseModel):
    success: bool
    result: str | None = Field(default=None, description="base64 cloudpickle")
    error: str | None = None
    stdout: str | None = None
    worker: dict[str, Any] | None = Field(
        default=None, description="Worker metadata (python version, gpu, timings)"
    )
