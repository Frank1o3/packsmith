# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import tomllib
from importlib.metadata import version
from pathlib import Path

from pyfiglet import Figlet
from rich.align import Align
from rich.console import Console, RenderableType
from rich.padding import Padding
from rich.style import Style
from rich.text import Text

from packsmith.core.models import LockFile, Manifest

console = Console()
__version__ = version("packsmith")


def _interp_rgb(
    c1: tuple[int, int, int], c2: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


start_rgb = (34, 193, 255)  # cyan-ish
end_rgb = (138, 43, 226)  # blueviolet / purple


def load_lock(path: Path) -> LockFile:
    if path.stat().st_size == 0:
        return LockFile()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return LockFile.model_validate(data)


# In ui.py


def print_banner() -> None:
    path = Path.cwd()
    info = _load_manifest(path)
    lock = _load_lock(path)

    # ASCII ART TITLE - Use block/big font
    title = _create_banner_title()

    pack_info = _create_pack_info(info, lock)

    panel = Padding(Text.from_markup(pack_info), (1, 2))

    console.print(title)
    console.print(panel)
    console.rule(style="bright_black")
    console.print("\n[dim]Use [cyan]--help[/cyan] to see available commands.[/dim]")


def _load_manifest(path: Path) -> Manifest | None:
    register_file = path / "meta.json"
    if register_file.exists():
        return Manifest.model_validate_json(register_file.read_text("utf-8"))
    return None


def _load_lock(path: Path) -> LockFile | None:
    lock_file = path / "lock.toml"
    if lock_file.exists():
        return load_lock(lock_file)
    return None


def _create_banner_title() -> RenderableType:
    figlet = Figlet(font="doom")
    ascii_title = figlet.renderText("PACKSMITH").rstrip()
    version_line = f"v{__version__}"
    return Align.center(_render_gradient_banner(ascii_title, version_line))


def _render_gradient_banner(ascii_title: str, version_line: str) -> Text:
    """Return a `Text` with a horizontal gradient applied to the ASCII title.

    The version string is right-aligned on the first line and rendered with
    a bright accent color for emphasis.

    Returns
    -------
    Text
        A Rich `Text` object with styled gradient characters.


    """
    title_lines = ascii_title.split("\n")

    # Build a Text object with a horizontal gradient per character.
    start_rgb = (34, 193, 255)  # cyan-ish
    end_rgb = (138, 43, 226)  # blueviolet / purple

    # Determine max line length so we can right-align the version on the first line
    max_len = max(len(line) for line in title_lines) + 2 + len(version_line)

    banner_text = Text()
    for idx, line in enumerate(title_lines):
        # For the first line, append the version right-aligned
        if idx == 0:
            # pad line so version sits at the right
            padded = line.ljust(max_len - len(version_line)) + version_line
        else:
            padded = line.ljust(max_len)

        line_len = len(padded)
        if line_len <= 1:
            banner_text.append(padded + "\n")
            continue

        # If this is the top line, compute where the version text starts
        version_start = max_len - len(version_line) if idx == 0 else None

        for i, ch in enumerate(padded):
            t = i / (line_len - 1)
            color = _rgb_to_hex(_interp_rgb(start_rgb, end_rgb, t))
            # If this is the version area on the first line, use accent color
            if version_start is not None and i >= version_start:
                ver_color = "#9b59ff"
                if ch == " ":
                    banner_text.append(ch, style=Style(color=ver_color, dim=True))
                else:
                    banner_text.append(ch, style=Style(color=ver_color, bold=True))
                continue
            # Make spaces dimmer so the gradient reads on characters
            if ch == " ":
                banner_text.append(ch, style=Style(color=color, dim=True))
            else:
                banner_text.append(ch, style=Style(color=color, bold=True))

        if idx < len(title_lines) - 1:
            banner_text.append("\n")

    return banner_text


def _create_pack_info(info: Manifest | None, lock: LockFile | None) -> str:
    if not info:
        return "[dim]No pack detected in this directory[/dim]"

    pack_info = (
        f"[bold]Name:[/bold]             {info.name}\n"
        f"[bold]Game Version:[/bold]     {info.game_version}\n"
        f"[bold]Loader:[/bold]           {info.loader}\n"
        f"[bold]Loader Version:[/bold]   {info.loader_version}"
    )

    if lock is not None and getattr(lock, "packages", None):
        lock_versions = {
            pkg.project_id: pkg.version_number
            for pkg in lock.packages
            if pkg.version_number
        }
    else:
        lock_versions = {}

    mod_count = len(info.mods)
    mods_section = f"\n\n [bold cyan]Mods ({mod_count} shown):[/bold cyan]\n"

    if mod_count > 0:
        for mod in info.mods:
            mod_version = lock_versions.get(mod.project_id, "N/A")
            padded_name = f"{mod.name}{' ' * max(0, 44 - len(mod.name))}"
            mods_section += f"  • {padded_name}({mod_version})\n"
    else:
        mods_section += "  [dim]No mods added yet[/dim]\n"

    return pack_info + mods_section
