# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import asyncio
import hashlib
import hmac
import os
import tempfile
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
    name = fallback or Path(unquote(urlparse(url).path)).name
    name = Path(name).name
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


def _validate_file_hashes(path: Path, hashes: Hashes) -> bool:
    sha1 = hashlib.sha1() if hashes.sha1 else None
    sha512 = hashlib.sha512() if hashes.sha512 else None

    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            if sha1:
                sha1.update(chunk)
            if sha512:
                sha512.update(chunk)

    return not (
        (sha512 and not hmac.compare_digest(sha512.hexdigest(), hashes.sha512))
        or (sha1 and not hmac.compare_digest(sha1.hexdigest(), hashes.sha1))
    )


async def _ensure_dir(path: Path) -> None:
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)


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
        is_valid = await asyncio.to_thread(
            _validate_file_hashes, target_path, file.hashes
        )
        if is_valid:
            return package, target_path, "already downloaded"

    task_id = progress.add_task(
        "download",
        filename=filename,
        total=file.size or 0,
    )

    temp_file = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target_dir,
        prefix=f".{filename}.",
        suffix=".part",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    sha1 = hashlib.sha1() if file.hashes.sha1 else None
    sha512 = hashlib.sha512() if file.hashes.sha512 else None
    try:
        with temp_file:
            async with (
                semaphore,
                client.stream("GET", file.url, follow_redirects=True) as response,
            ):
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", file.size or 0))
                progress.update(task_id, total=total)
                async for chunk in response.aiter_bytes(65536):
                    if not chunk:
                        continue
                    temp_file.write(chunk)
                    if sha1:
                        sha1.update(chunk)
                    if sha512:
                        sha512.update(chunk)
                    progress.update(task_id, advance=len(chunk))

        if (
            sha512 and not hmac.compare_digest(sha512.hexdigest(), file.hashes.sha512)
        ) or (sha1 and not hmac.compare_digest(sha1.hexdigest(), file.hashes.sha1)):
            message = f"Hash mismatch for {package.project_id} ({filename})."
            raise RuntimeError(message)

        os.replace(temp_path, target_path)
        progress.update(task_id, completed=total)
    finally:
        temp_path.unlink(missing_ok=True)

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
        headers={"User-Agent": user_agent, "Accept": "application/octet-stream"},
        timeout=timeout,
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
