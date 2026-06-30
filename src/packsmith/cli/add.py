# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import asyncio
import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

import tomli_w
import typer
from rich.table import Table

from packsmith.api import ModrinthClient
from packsmith.cli.ui import console
from packsmith.core.models import (
    ERROR_NOT_IN_PACK,
    PROJECT_TYPE_TO_FIELD,
    Hit,
    LockFile,
    LockPackage,
    Manifest,
    MatchResults,
    MatchScore,
    ProjectType,
    Search,
)

USER_AGENT = (
    f"Frank1o3/packsmith/{version('packsmith')} (https://github.com/Frank1o3/packsmith)"
)

if TYPE_CHECKING:
    from rich.console import Console


async def search(
    name: str, project_type: ProjectType, loader: str, game_version: str
) -> Search:
    client = ModrinthClient(USER_AGENT)
    return await client.search(name, project_type, loader, game_version)


def load_lock(path: Path) -> LockFile:
    if path.stat().st_size == 0:
        return LockFile()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return LockFile.model_validate(data)


def save_lock(path: Path, lock: LockFile) -> None:
    with path.open("wb") as f:
        tomli_w.dump(lock.model_dump(exclude_none=True), f)


def save_manifest(path: Path, manifest: Manifest) -> None:
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def has_package(lock: LockFile, project_id: str) -> bool:
    return any(pkg.project_id == project_id for pkg in lock.package)


def select_match(matched: MatchResults, console: Console) -> Hit:
    if not matched.results:
        console.print("[red]No matches found.[/red]")
        raise typer.Exit(code=1)

    table = Table(title="Select a mod", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", style="cyan")
    table.add_column("Slug", style="dim")
    table.add_column("Confidence", justify="right")

    for i, result in enumerate(matched.results, start=1):
        hit = result.hit
        score = result.score

        if score >= MatchScore.ACRONYM:
            style = "green"
        elif score >= MatchScore.PREFIX:
            style = "yellow"
        else:
            style = "red"

        table.add_row(str(i), hit.title, hit.slug, f"[{style}]{score}[/]")

    console.print(table)

    choice = typer.prompt("Select a mod by number", type=int)

    if choice < 1 or choice > len(matched.results):
        console.print("[red]Invalid selection.[/red]")
        raise typer.Exit(code=1)

    return matched.results[choice - 1].hit


def apply_add(
    info: Manifest,
    lock: LockFile,
    hit: Hit,
) -> None:
    field_name = PROJECT_TYPE_TO_FIELD.get(hit.project_type)

    if field_name is None:
        err = f"Unsupported project type: {hit.project_type}"
        raise ValueError(err)

    target_list: list[str] = getattr(info, field_name)

    if hit.title not in target_list:
        target_list.append(hit.title)

    if not has_package(lock, hit.project_id):
        lock.package.append(
            LockPackage(
                name=hit.title, project_id=hit.project_id, project_type=hit.project_type
            )
        )


def resolve_hit(matched: MatchResults, console: Console) -> Hit | None:
    if not matched.results:
        console.print("[red]No matches found.[/red]")
        raise typer.Exit(code=1)

    if matched.best and matched.best.score == MatchScore.EXACT:
        return matched.best.hit

    return select_match(matched, console)


def add(name: str, project_type: ProjectType) -> None:
    path = Path.cwd()
    register_file = path / "meta.json"
    lock_file = path / "lock.toml"

    if not register_file.exists() or not lock_file.exists():
        raise RuntimeError(ERROR_NOT_IN_PACK)

    info = Manifest.model_validate_json(register_file.read_text("utf-8"))
    lock = load_lock(lock_file)

    search_res = asyncio.run(search(name, project_type, info.loader, info.game_version))
    matched = search_res.match(name, project_type)

    hit = resolve_hit(matched, console)

    if hit is None:
        raise typer.Exit

    apply_add(info, lock, hit)

    save_manifest(register_file, info)
    save_lock(lock_file, lock)
