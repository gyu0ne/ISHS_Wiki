from __future__ import annotations

import ast
import builtins
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import socket
import subprocess
from types import MappingProxyType, ModuleType
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
Definition = type | Callable[..., str | bytes | int | tuple] | str | int | bool
Dependency = Definition | ModuleType | Mapping[str, str | int | bool] | None


class FixtureBoundaryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceTrace:
    path: str
    sha256: str
    definitions: tuple[str, ...]
    loader_guard_calls: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class LoadedSource:
    definitions: Mapping[str, Definition]
    trace: SourceTrace


@contextmanager
def side_effect_guard() -> Iterator[Counter[str]]:
    calls: Counter[str] = Counter()
    real_import = builtins.__import__
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            calls["write"] += 1
            raise FixtureBoundaryError("loader write denied")
        return real_open(file, mode, *args, **kwargs)

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pip" or name.startswith("pip."):
            calls["pip"] += 1
            raise FixtureBoundaryError("loader pip import denied")
        return real_import(name, globals, locals, fromlist, level)

    def deny_network(*_args, **_kwargs):
        calls["network"] += 1
        raise FixtureBoundaryError("loader network denied")

    def deny_subprocess(*_args, **_kwargs):
        calls["subprocess"] += 1
        raise FixtureBoundaryError("loader subprocess denied")

    with (
        patch("builtins.open", guarded_open),
        patch.object(io, "open", guarded_open),
        patch("builtins.__import__", guarded_import),
        patch.object(socket, "socket", deny_network),
        patch.object(socket, "create_connection", deny_network),
        patch.object(subprocess, "Popen", deny_subprocess),
    ):
        yield calls


def _resolved_source(source: Path) -> Path:
    resolved = source.resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise FixtureBoundaryError(f"outside source root: {source}")
    return resolved


def _validate_definition(node: ast.AST) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        evaluated = [*node.decorator_list, *node.args.defaults]
        evaluated.extend(default for default in node.args.kw_defaults if default is not None)
        if any(isinstance(child, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom)) for item in evaluated for child in ast.walk(item)):
            raise FixtureBoundaryError("definition-time execution denied")
        return
    if isinstance(node, ast.ClassDef):
        if node.bases or node.keywords or node.decorator_list:
            raise FixtureBoundaryError("class definition-time execution denied")
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _validate_definition(item)
            elif not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant)) and not isinstance(item, ast.Pass):
                raise FixtureBoundaryError("executable class body denied")
        return
    if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
        raise FixtureBoundaryError("unsupported source definition")
    try:
        ast.literal_eval(node.value)
    except (ValueError, TypeError) as error:
        raise FixtureBoundaryError("non-literal assignment denied") from error


def load_source_definitions(
    source: Path,
    names: tuple[str, ...],
    dependencies: Mapping[str, Dependency],
) -> LoadedSource:
    """Compile named top-level definitions while trapping loader side effects."""
    resolved = _resolved_source(source)
    raw = resolved.read_bytes()
    tree = ast.parse(raw, filename=str(resolved))
    requested = set(names)
    selected: list[ast.stmt] = []
    found: set[str] = set()
    for node in tree.body:
        node_names: set[str] = set()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node_names.add(node.name)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            node_names.update(target.id for target in targets if isinstance(target, ast.Name))
        if node_names & requested:
            _validate_definition(node)
            selected.append(node)
            found.update(node_names & requested)
    missing = requested - found
    if missing:
        raise FixtureBoundaryError(f"definitions not found: {', '.join(sorted(missing))}")
    namespace = dict(dependencies)
    with side_effect_guard() as calls:
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(resolved), "exec"), namespace)
    definitions = MappingProxyType({name: namespace[name] for name in names})
    trace = SourceTrace(
        str(resolved.relative_to(ROOT)),
        hashlib.sha256(raw).hexdigest(),
        names,
        tuple(sorted(calls.items())),
    )
    return LoadedSource(definitions, trace)
