"""Extract a decorated function's source and its local-module closure.

Adapted from runpod-flash (MIT, Copyright (c) 2026 Runpod).
"""

import ast
import inspect
import logging
import textwrap
from pathlib import Path

from .exceptions import LocalModulePayloadTooLargeError
from .local_modules import MAX_INLINE_MODULE_BYTES, resolve_local_modules

log = logging.getLogger(__name__)


def get_function_source(func) -> str:
    """Return the function's source without its decorators."""
    func = inspect.unwrap(func)
    source = textwrap.dedent(inspect.getsource(func))
    module = ast.parse(source)

    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.__name__:
            # node.lineno points at the `def`/`async def` line, past decorators.
            lines = source.split("\n")[node.lineno - 1 :]
            return textwrap.dedent("\n".join(lines))

    raise ValueError(f"Could not find function definition for {func.__name__}")


def build_modules_map(func_source: str, source_file: str | None) -> dict[str, str]:
    """Collect the source of local modules the function imports, for inline shipping."""
    if not source_file:
        return {}

    project_root = Path(source_file).resolve().parent
    resolved = resolve_local_modules(func_source, source_file, project_root)
    for warning in resolved.warnings:
        log.warning(warning)

    modules: dict[str, str] = {}
    total = len(func_source.encode("utf-8"))
    for rel_path, abs_path in resolved.files.items():
        text = Path(abs_path).read_text(encoding="utf-8")
        total += len(text.encode("utf-8"))
        modules[rel_path] = text

    if total > MAX_INLINE_MODULE_BYTES:
        raise LocalModulePayloadTooLargeError(
            f"Inline module payload is {total} bytes, over the {MAX_INLINE_MODULE_BYTES}-byte cap."
        )
    return modules
