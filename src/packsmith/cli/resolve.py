# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
import asyncio
import sys
from pathlib import Path

import click

from packsmith.cli.ui import console
from packsmith.core.models import LockFile, Manifest
from packsmith.core.solver import Resolver

MANIFEST_FILE = "meta.json"
LOCK_FILE = "packsmith.lock.json"


@click.command()
@click.option(
    "--include-optional",
    is_flag=True,
    default=False,
    help="Include optional dependencies during resolution.",
)
def resolve(*, include_optional: bool = False) -> None:
    """Resolve all dependencies for the current modpack."""
    manifest_path = Path(MANIFEST_FILE)
    lock_path = Path(LOCK_FILE)

    if not manifest_path.exists():
        console.print(
            "[red]Error:[/red] Not inside a Packsmith project (meta.json not found)."
        )
        sys.exit(1)

    if not lock_path.exists():
        console.print("[red]Error:[/red] Missing lock file.")
        sys.exit(1)

    manifest = Manifest.model_validate_json(manifest_path.read_text("UTF-8"))
    lock = LockFile.model_validate_json(lock_path.read_text("UTF-8"))

    resolver = Resolver(manifest, include_optional=include_optional)

    async def _write_lock() -> None:
        await asyncio.to_thread(
            lock_path.write_text,
            lock.model_dump_json(indent=2),
            "utf-8",
        )

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

    if failed > 0:
        console.print(
            "\n[bold yellow]Warning: The following packages failed to "
            "resolve:[/bold yellow]"
        )
        for pkg in lock.packages:
            if pkg.state == "failed":
                console.print(f"  • {pkg.project_id}")
