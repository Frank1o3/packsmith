# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import asyncio
import sys
import tomllib
from pathlib import Path

import tomli_w
import typer

from packsmith.cli.ui import console
from packsmith.core.models import LockFile, Manifest
from packsmith.core.solver import Resolver


def load_lock(path: Path) -> LockFile:
    if path.stat().st_size == 0:
        return LockFile()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return LockFile.model_validate(data)


def save_lock(path: Path, lock: LockFile) -> None:
    with path.open("wb") as f:
        tomli_w.dump(lock.model_dump(exclude_none=True), f)


def resolve(  # noqa: C901
    *,
    include_optional: bool = typer.Option(
        default=False,
        help="Include optional dependencies during resolution.",
    ),
) -> None:
    """Resolve all dependencies for the current modpack."""
    path = Path.cwd()
    register_file = path / "meta.json"
    lock_file = path / "lock.toml"

    if not register_file.exists():
        console.print(
            "[red]Error:[/red] Not inside a Packsmith project (meta.json not found)."
        )
        typer.Exit(code=1)

    if not lock_file.exists():
        console.print("[red]Error:[/red] Missing lock file.")
        typer.Exit(code=1)

    manifest = Manifest.model_validate_json(register_file.read_text("UTF-8"))
    lock = load_lock(lock_file)

    resolver = Resolver(manifest, include_optional=include_optional)

    async def _write_lock() -> None:
        await asyncio.to_thread(save_lock, lock_file, lock)

    async def _run() -> None:
        console.print("Resolving root packages...")
        await resolver.first_layer(lock)

        console.print("Writing lock file...")
        await _write_lock()

        console.print("Resolving dependency graph...")
        await resolver.second_layer(lock)

        console.print("Writing lock file...")
        await _write_lock()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Resolution interrupted by user.[/yellow]")
        sys.exit(130)

    # Compute summary directly from lock file states
    resolved = sum(1 for pkg in lock.packages if pkg.state == "resolved")
    failed = sum(1 for pkg in lock.packages if pkg.state == "failed")
    pending = sum(1 for pkg in lock.packages if pkg.state == "pending")

    console.print("\n[bold green]✓ Dependency resolution complete[/bold green]\n")
    console.print(f"Resolved packages : {resolved}")
    console.print(f"Failed packages   : {failed}")
    console.print(f"Pending packages  : {pending}")

    if resolver.warnings:
        console.print("\n[bold yellow]Warnings:[/bold yellow]")
        for warning in resolver.warnings:
            console.print(f"  • {warning}")

    if failed > 0:
        console.print(
            "\n[bold yellow]Warning: The following packages failed to "
            "resolve:[/bold yellow]"
        )
        for pkg in lock.packages:
            if pkg.state == "failed":
                console.print(f"  • {pkg.project_id}")
