# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT


import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

import typer

from packsmith.cli.ui import console
from packsmith.core.models import (
    Env,
    LockFile,
    LockPackage,
    Manifest,
    ModPack,
    ModPackFile,
)


def load_lock(path: Path) -> LockFile:
    if path.stat().st_size == 0:
        return LockFile()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return LockFile.model_validate(data)


def _get_export_path(package: LockPackage, path: Path) -> Path:
    if package.project_type == "resourcepack":
        return path / "overrides" / "resourcepacks"
    if package.project_type == "shader":
        return path / "overrides" / "shaderpacks"
    return path / "mods"


def build_pack_file(
    manifest: Manifest, lock: LockFile, *, client_side: bool, server_side: bool
) -> ModPack:
    """Build a ModPackFile from the given manifest and lock file.

    Returns:
        A ModPackFile object representing the modpack.

    """
    pack = ModPack(name=manifest.name)

    for package in lock.packages:
        if (
            package.file is None
            or package.project_type is None
            or package.client_side is None
            or package.server_side is None
        ):
            continue

        if not client_side and package.client_side in {"required", "optional"}:
            continue

        if not server_side and package.server_side in {"required", "optional"}:
            continue

        filename = (
            package.file.filename
            or Path(unquote(urlparse(package.file.url).path)).name
            or "downloaded.file"
        )
        source_path = _get_export_path(package, Path.cwd()) / filename
        path = source_path.relative_to(Path.cwd()).as_posix()
        pack.files.append(
            ModPackFile(
                env=Env(client=package.client_side, server=package.server_side),
                hashes=package.file.hashes,
                path=path.removeprefix("overrides/")
                if path.startswith("overrides/")
                else path,
                downloads=[package.file.url],
                fileSize=package.file.size,
            )
        )

    pack.dependencies = {
        f"{manifest.loader}-loader": manifest.loader_version,
        "minecraft": manifest.game_version,
    }

    return pack


def export_pack(
    manifest: Manifest,
    lock: LockFile,
    side: Literal["client", "server", "both"] = "both",
) -> None:
    """Export a modpack archive for the requested side.

    Exit: If the pack is not created in a valid project directory.
    """
    path = Path.cwd()

    register_file = path / "meta.json"
    lock_file = path / "lock.toml"
    pack_file = path / "modrinth.index.json"

    pack_file.touch(exist_ok=True)

    pack = build_pack_file(
        manifest,
        lock,
        client_side=side in {"client", "both"},
        server_side=side in {"server", "both"},
    )
    pack_file.write_text(pack.model_dump_json(indent=2), encoding="UTF-8")
    tag = f"-{side}" if side != "both" else ""
    export_path = path / f"{manifest.name}{tag}.mrpack"

    with ZipFile(export_path, "w", compression=ZIP_DEFLATED) as zip_file:
        zip_file.write(pack_file, arcname="modrinth.index.json")
        zip_file.write(register_file, arcname="meta.json")
        zip_file.write(lock_file, arcname="lock.toml")

        # Create the directory structure for mods, resourcepacks, and shaderpacks
        zip_file.writestr("mods/", "")
        zip_file.writestr("overrides/resourcepacks/", "")
        zip_file.writestr("overrides/shaderpacks/", "")
        zip_file.writestr("overrides/config/", "")

        # Copy the files from the mods, resourcepacks,
        # and shaderpacks directories into the zip file that are compatible
        # we can use the data in pack.files,
        # to determine which files to include in the zip file

        for file in pack.files:
            source_path = path / file.path
            if source_path.exists():
                zip_file.write(source_path, arcname=file.path)

        # lastly, we can copy all the files found in the config dir to the zip version
        config_dir = path / "overrides" / "config"
        if config_dir.exists():
            for config_file in config_dir.rglob("*"):
                if config_file.is_file():
                    arcname = f"overrides/config/{config_file.relative_to(config_dir)}"
                    zip_file.write(config_file, arcname=arcname)
    msg = side if side != "both" else "client and server"
    console.print(f"[green]Exported {msg} modpack:[/green] {export_path.name}")


def export(
    *,
    client: bool = typer.Option(
        default=False,
        help="Export a client-side modpack.",
    ),
    server: bool = typer.Option(
        default=False,
        help="Export a server-side modpack.",
    ),
) -> None:
    """Export a modpack for distribution.

    Raises:
        Exit: If no side flag is provided or the project is invalid.


    """
    side: Literal["client", "server", "both"]
    if client and server:
        side = "both"
    elif client:
        side = "client"
    elif server:
        side = "server"
    else:
        console.print("[red]Error:[/red] Must specify either --client or --server.")
        raise typer.Exit(code=1)

    path = Path.cwd()
    register_file = path / "meta.json"
    lock_file = path / "lock.toml"

    if not register_file.exists():
        console.print(
            "[red]Error:[/red] Not inside a Packsmith project (meta.json not found)."
        )
        raise typer.Exit(code=1)

    if not lock_file.exists():
        console.print("[red]Error:[/red] Missing lock file.")
        raise typer.Exit(code=1)

    manifest = Manifest.model_validate_json(register_file.read_text("UTF-8"))
    lock = load_lock(lock_file)

    export_pack(manifest, lock, side=side)
