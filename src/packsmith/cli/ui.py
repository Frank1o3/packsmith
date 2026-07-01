# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

from importlib.metadata import version
from pathlib import Path

from pyfiglet import Figlet
from rich.align import Align
from rich.console import Console
from rich.panel import Panel

from packsmith.core.models import Manifest

console = Console()
__version__ = version("packsmith")


def print_banner() -> None:
    path = Path.cwd()
    register_file = path / "meta.json"

    info: Manifest | None = None
    if register_file.exists():
        info = Manifest.model_validate_json(register_file.read_text("utf-8"))

    # ASCII ART TITLE
    figlet = Figlet(font="slant")
    ascii_title = figlet.renderText("Packsmith")

    title = Align.center(f"[cyan]{ascii_title}[/cyan]")
    version_text = Align.center(f"[dim]v{__version__}[/dim]")

    if info:
        # Base info (matches your screenshot layout)
        pack_info = (
            f"[bold]Name:[/bold] {info.name}\n"
            f"[bold]Game Version:[/bold] {info.game_version}\n"
            f"[bold]Loader:[/bold] {info.loader}\n"
            f"[bold]Loader Version:[/bold] {info.loader_version}"
        )

        # Mods section
        mod_count = len(info.mods)
        mods_section = f"\n\n[bold cyan]Mods ({mod_count} shown):[/bold cyan]\n"

        if mod_count > 0:
            for mod in info.mods:
                mods_section += f"  • {mod}\n"
        else:
            mods_section += "  [dim]No mods added yet[/dim]\n"

        pack_info += mods_section

    else:
        pack_info = "[dim]No pack detected in this directory[/dim]"

    panel = Panel(
        pack_info,
        border_style="cyan",
        padding=(1, 2),
        expand=True,
    )

    console.print(title)
    console.print(version_text)
    console.print(panel)
