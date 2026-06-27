#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BACKEND_REPO = Path("/home/nimrodbu/Traigent_enterprise/TraigentBackend")
DEFAULT_REF = "origin/develop"
DEFAULT_OUT = Path("tests/data/backend_routes_snapshot.json")
REPO_SLUG = "Traigent/TraigentBackend"
HTTP_SHORTHANDS = {"get", "post", "put", "patch", "delete"}
ROOT_BLUEPRINT = ("src/app.py", "app")


@dataclass(frozen=True, slots=True)
class BlueprintInfo:
    key: tuple[str, str]
    name: str
    url_prefix: str
    source_file: str


@dataclass(frozen=True, slots=True)
class RouteInfo:
    method: str
    path: str
    blueprint_key: tuple[str, str]
    source_file: str


@dataclass(frozen=True, slots=True)
class Registration:
    parent_key: tuple[str, str]
    child_key: tuple[str, str]
    url_prefix: str | None


@dataclass(slots=True)
class ModuleFacts:
    source_file: str
    imports: dict[str, tuple[str, str]]
    constants: dict[str, tuple[str, ...]]
    blueprints: dict[tuple[str, str], BlueprintInfo]
    routes: list[RouteInfo]
    registrations: list[Registration]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the vendored TraigentBackend route snapshot from git refs.",
    )
    parser.add_argument("--repo", type=Path, default=DEFAULT_BACKEND_REPO)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    snapshot = build_snapshot(repo=args.repo, ref=args.ref)
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {out.as_posix()} with {len(snapshot['routes'])} routes "
        f"from {snapshot['generated_from']['commit_sha']}",
    )
    return 0


def build_snapshot(*, repo: Path, ref: str) -> dict[str, Any]:
    commit_sha = _git(repo, "rev-parse", ref).strip()
    source_files = ["src/app.py", *_route_files(repo, ref)]
    module_facts = [
        _parse_source(repo=repo, ref=ref, source_file=source_file)
        for source_file in source_files
    ]

    blueprints: dict[tuple[str, str], BlueprintInfo] = {
        ROOT_BLUEPRINT: BlueprintInfo(
            key=ROOT_BLUEPRINT,
            name="app",
            url_prefix="",
            source_file="src/app.py",
        )
    }
    routes: list[RouteInfo] = []
    registrations: list[Registration] = []
    for facts in module_facts:
        blueprints.update(facts.blueprints)
        routes.extend(facts.routes)
        registrations.extend(facts.registrations)

    mount_prefixes = _mount_prefixes(blueprints, registrations)
    route_records: set[tuple[str, str, str, str]] = set()
    for route in routes:
        blueprint = blueprints.get(route.blueprint_key)
        if blueprint is None:
            continue
        for mount_prefix in mount_prefixes.get(route.blueprint_key, ()):
            route_records.add(
                (
                    route.method,
                    _join_paths(mount_prefix, route.path),
                    blueprint.name,
                    route.source_file,
                )
            )

    return {
        "generated_from": {
            "repo": REPO_SLUG,
            "ref": ref,
            "commit_sha": commit_sha,
        },
        "routes": [
            {
                "method": method,
                "path_template": path_template,
                "blueprint": blueprint,
                "source_file": source_file,
            }
            for method, path_template, blueprint, source_file in sorted(route_records)
        ],
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True)


def _route_files(repo: Path, ref: str) -> list[str]:
    output = _git(repo, "ls-tree", "--name-only", ref, "src/routes/")
    return sorted(line for line in output.splitlines() if line.endswith(".py"))


def _parse_source(*, repo: Path, ref: str, source_file: str) -> ModuleFacts:
    text = _git(repo, "show", f"{ref}:{source_file}")
    tree = ast.parse(text, filename=source_file)
    imports = _collect_route_imports(tree)
    constants = _collect_constants(tree)

    blueprints: dict[tuple[str, str], BlueprintInfo] = {}
    routes: list[RouteInfo] = []
    registrations: list[Registration] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            blueprint = _blueprint_from_assignment(node, source_file=source_file)
            if blueprint is not None:
                blueprints[blueprint.key] = blueprint

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            routes.extend(
                _routes_from_function(
                    node,
                    source_file=source_file,
                    imports=imports,
                    blueprints=blueprints,
                    constants=constants,
                )
            )
        elif isinstance(node, ast.Call):
            registration = _registration_from_call(
                node,
                source_file=source_file,
                imports=imports,
                blueprints=blueprints,
            )
            if registration is not None:
                registrations.append(registration)

    return ModuleFacts(
        source_file=source_file,
        imports=imports,
        constants=constants,
        blueprints=blueprints,
        routes=routes,
        registrations=registrations,
    )


def _collect_route_imports(tree: ast.AST) -> dict[str, tuple[str, str]]:
    imports: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("src.routes."):
            continue
        route_module = node.module.removeprefix("src.routes.")
        if "." in route_module:
            continue
        source_file = f"src/routes/{route_module}.py"
        for alias in node.names:
            if alias.name == "*":
                continue
            imports[alias.asname or alias.name] = (source_file, alias.name)
    return imports


def _collect_constants(tree: ast.AST) -> dict[str, tuple[str, ...]]:
    constants: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        values = _string_sequence(node.value, constants)
        if values is None:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = values
    return constants


def _blueprint_from_assignment(
    node: ast.Assign, *, source_file: str
) -> BlueprintInfo | None:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return None
    call = node.value
    if not isinstance(call, ast.Call):
        return None
    if not _is_blueprint_constructor(call.func):
        return None

    var_name = node.targets[0].id
    blueprint_name = _literal_string(call.args[0]) if call.args else None
    url_prefix = _keyword_string(call, "url_prefix") or ""
    return BlueprintInfo(
        key=(source_file, var_name),
        name=blueprint_name or var_name,
        url_prefix=url_prefix,
        source_file=source_file,
    )


def _is_blueprint_constructor(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id in {"Blueprint", "create_api_blueprint"}
    if isinstance(func, ast.Attribute):
        return func.attr in {"Blueprint", "create_api_blueprint"}
    return False


def _routes_from_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    source_file: str,
    imports: dict[str, tuple[str, str]],
    blueprints: dict[tuple[str, str], BlueprintInfo],
    constants: dict[str, tuple[str, ...]],
) -> list[RouteInfo]:
    routes: list[RouteInfo] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Attribute):
            continue

        route_attr = decorator.func.attr
        if route_attr != "route" and route_attr not in HTTP_SHORTHANDS:
            continue

        owner = _name_from_expr(decorator.func.value)
        if owner is None:
            continue
        if owner == "app" and source_file == "src/app.py":
            blueprint_key = ROOT_BLUEPRINT
        else:
            blueprint_key = _resolve_blueprint_name(
                owner, source_file, imports, blueprints
            )
            if blueprint_key is None:
                continue

        path = _literal_string(decorator.args[0]) if decorator.args else None
        if path is None:
            continue

        methods = (
            (route_attr.upper(),)
            if route_attr in HTTP_SHORTHANDS
            else _route_methods(decorator, constants)
        )
        for method in methods:
            routes.append(
                RouteInfo(
                    method=method,
                    path=path,
                    blueprint_key=blueprint_key,
                    source_file=source_file,
                )
            )
    return routes


def _registration_from_call(
    node: ast.Call,
    *,
    source_file: str,
    imports: dict[str, tuple[str, str]],
    blueprints: dict[tuple[str, str], BlueprintInfo],
) -> Registration | None:
    if (
        not isinstance(node.func, ast.Attribute)
        or node.func.attr != "register_blueprint"
    ):
        return None
    if not node.args:
        return None

    parent_name = _name_from_expr(node.func.value)
    child_name = _name_from_expr(node.args[0])
    if parent_name is None or child_name is None:
        return None

    if parent_name == "app" and source_file == "src/app.py":
        parent_key = ROOT_BLUEPRINT
    else:
        resolved_parent = _resolve_blueprint_name(
            parent_name, source_file, imports, blueprints
        )
        if resolved_parent is None:
            return None
        parent_key = resolved_parent

    child_key = _resolve_blueprint_name(child_name, source_file, imports, blueprints)
    if child_key is None:
        return None

    return Registration(
        parent_key=parent_key,
        child_key=child_key,
        url_prefix=_keyword_string(node, "url_prefix"),
    )


def _resolve_blueprint_name(
    name: str,
    source_file: str,
    imports: dict[str, tuple[str, str]],
    blueprints: dict[tuple[str, str], BlueprintInfo],
) -> tuple[str, str] | None:
    if name in imports:
        return imports[name]
    key = (source_file, name)
    if key in blueprints:
        return key
    return None


def _mount_prefixes(
    blueprints: dict[tuple[str, str], BlueprintInfo],
    registrations: list[Registration],
) -> dict[tuple[str, str], tuple[str, ...]]:
    children_by_parent: dict[tuple[str, str], list[Registration]] = {}
    for registration in registrations:
        children_by_parent.setdefault(registration.parent_key, []).append(registration)

    discovered: dict[tuple[str, str], set[str]] = {ROOT_BLUEPRINT: {""}}
    queue: list[tuple[str, str]] = [ROOT_BLUEPRINT]
    while queue:
        parent_key = queue.pop(0)
        for registration in sorted(
            children_by_parent.get(parent_key, ()),
            key=lambda item: (item.child_key, item.url_prefix or ""),
        ):
            child = blueprints.get(registration.child_key)
            if child is None:
                continue
            child_segment = (
                registration.url_prefix
                if registration.url_prefix is not None
                else child.url_prefix
            )
            for parent_prefix in discovered.get(parent_key, ()):
                mount = _join_paths(parent_prefix, child_segment)
                known = discovered.setdefault(registration.child_key, set())
                if mount not in known:
                    known.add(mount)
                    queue.append(registration.child_key)

    return {key: tuple(sorted(values)) for key, values in discovered.items()}


def _route_methods(
    call: ast.Call, constants: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    for keyword in call.keywords:
        if keyword.arg != "methods":
            continue
        values = _string_sequence(keyword.value, constants)
        if values:
            return tuple(method.upper() for method in values)
    return ("GET",)


def _string_sequence(
    node: ast.AST, constants: dict[str, tuple[str, ...]]
) -> tuple[str, ...] | None:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: list[str] = []
        for item in node.elts:
            literal = _literal_string(item)
            if literal is None:
                return None
            values.append(literal)
        return tuple(values)
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    return None


def _keyword_string(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return _literal_string(keyword.value)
    return None


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _name_from_expr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _join_paths(*parts: str | None) -> str:
    cleaned: list[str] = []
    preserve_trailing = False
    non_empty = [part for part in parts if part is not None and str(part) != ""]
    for index, raw in enumerate(non_empty):
        part = str(raw)
        is_last = index == len(non_empty) - 1
        if part == "/":
            preserve_trailing = is_last
            continue
        if is_last and part.endswith("/"):
            preserve_trailing = True
        stripped = part.strip("/")
        if stripped:
            cleaned.append(stripped)
    joined = "/" + "/".join(cleaned)
    if preserve_trailing and joined != "/":
        return f"{joined}/"
    return joined


if __name__ == "__main__":
    raise SystemExit(main())
