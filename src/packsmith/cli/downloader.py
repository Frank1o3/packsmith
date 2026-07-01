# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import asyncio
import hashlib
import hmac
import tomllib
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from packsmith.cli.ui import console
from packsmith.core.models import Hashes, LockFile, LockPackage

user_agent = (
    f"Frank1o3/packsmith/{version('packsmith')} (https://github.com/Frank1o3/packsmith)"
)


def load_lock(path: Path) -> LockFile:
    if path.stat().st_size == 0:
        return LockFile()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return LockFile.model_validate(data)


def _get_filename_from_url(url: str, *, fallback: str | None = None) -> str:
    if fallback:
        return fallback

    name = Path(unquote(urlparse(url).path)).name
    if not name:
        name = unquote(url.rsplit("/", maxsplit=1)[-1])
    return name or "downloaded.file"


def _get_package_dir(
    package: LockPackage,
    mods_dir: Path,
    resourcepacks_dir: Path,
    shaders_dir: Path,
) -> Path:
    if package.project_type == "resourcepack":
        return resourcepacks_dir
    if package.project_type == "shader":
        return shaders_dir
    return mods_dir


def _validate_hashes(data: bytes, hashes: Hashes) -> bool:
    if hashes.sha512:
        actual_sha512 = hashlib.sha512(data).hexdigest()
        if not hmac.compare_digest(actual_sha512, hashes.sha512):
            return False

    if hashes.sha1:
        actual_sha1 = hashlib.new("sha1", data).hexdigest()
        if not hmac.compare_digest(actual_sha1, hashes.sha1):
            return False

    return True


async def _ensure_dir(path: Path) -> None:
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)


async def _read_file_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


async def _write_file_bytes(path: Path, data: bytes) -> None:
    await asyncio.to_thread(path.write_bytes, data)


async def _download_package(
    client: httpx.AsyncClient,
    package: LockPackage,
    target_dir: Path,
    progress: Progress,
    semaphore: asyncio.Semaphore,
) -> tuple[LockPackage, Path, str | None]:
    if package.file is None:
        message = f"Package {package.project_id} has no download file."
        raise RuntimeError(message)

    file = package.file
    filename = _get_filename_from_url(file.url, fallback=file.filename)
    target_path = target_dir / filename
    await _ensure_dir(target_dir)

    if target_path.exists():
        existing_data = await _read_file_bytes(target_path)
        if _validate_hashes(existing_data, file.hashes):
            return package, target_path, "already downloaded"

    task_id = progress.add_task(
        "download",
        filename=filename,
        total=file.size or 0,
    )

    async with semaphore, client.stream("GET", file.url) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", file.size or 0))
        progress.update(task_id, total=total)
        data = bytearray()

        async for chunk in response.aiter_bytes(65536):
            if not chunk:
                continue
            data.extend(chunk)
            progress.update(task_id, advance=len(chunk))

    final_data = bytes(data)
    await _write_file_bytes(target_path, final_data)
    progress.update(task_id, completed=total)

    if not _validate_hashes(final_data, file.hashes):
        target_path.unlink(missing_ok=True)
        message = f"Hash mismatch for {package.project_id} ({filename})."
        raise RuntimeError(message)

    return package, target_path, None


async def _download_all(
    lock: LockFile,
    mods_dir: Path,
    resourcepacks_dir: Path,
    shaders_dir: Path,
) -> None:
    packages = [
        pkg for pkg in lock.packages if pkg.state == "resolved" and pkg.file is not None
    ]
    if not packages:
        console.print(
            "[yellow]No resolved packages with download files found.[/yellow]"
        )
        return

    timeout = httpx.Timeout(60.0, connect=15.0)
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent}, timeout=timeout
    ) as client:
        with Progress(
            TextColumn("{task.fields[filename]}", justify="left"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            tasks = []
            for package in packages:
                target_dir = _get_package_dir(
                    package, mods_dir, resourcepacks_dir, shaders_dir
                )
                tasks.append(
                    _download_package(client, package, target_dir, progress, semaphore)
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)

    failures = 0
    for result in results:
        if isinstance(result, BaseException):
            failures += 1
            console.print(f"[red]Download failed:[/red] {result}")
            continue

        package, path, message = result
        if message:
            console.print(f"[cyan]Skipped existing file:[/cyan] {path.name}")
        else:
            console.print(f"[green]Downloaded:[/green] {path.name}")

    if failures:
        message = f"{failures} file(s) failed to download."
        raise RuntimeError(message)


def download() -> None:
    """Download all dependencies for the current modpack.

    Raises:
        Exit: If the download fails or the project is invalid.

    """
    path = Path.cwd()
    register_file = path / "meta.json"
    lock_file = path / "lock.toml"
    mods_dir = path / "mods"
    resourcepacks_dir = path / "overrides" / "resourcepacks"
    shaders_dir = path / "overrides" / "shaderpacks"

    if not register_file.exists():
        console.print(
            "[red]Error:[/red] Not inside a Packsmith project (meta.json not found)."
        )
        raise typer.Exit(code=1)

    if not lock_file.exists():
        console.print("[red]Error:[/red] Missing lock file.")
        raise typer.Exit(code=1)

    lock = load_lock(lock_file)

    try:
        asyncio.run(_download_all(lock, mods_dir, resourcepacks_dir, shaders_dir))
    except Exception as exc:
        console.print(f"[red]Download failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
