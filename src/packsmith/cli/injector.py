# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import contextlib
import hashlib
import re
import secrets
import tempfile
import tomllib
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

import tomli_w
import typer

from packsmith.cli.ui import console
from packsmith.core.models import (
    Environment,
    File,
    Hashes,
    LockFile,
    LockPackage,
    ProjectType,
)

# 1GB safety limit (adjust if needed)
MAX_FILE_SIZE = 1024 * 1024 * 1024


def load_lock(path: Path) -> LockFile:
    if path.stat().st_size == 0:
        return LockFile()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return LockFile.model_validate(data)


def save_lock(path: Path, lock: LockFile) -> None:
    with path.open("wb") as f:
        tomli_w.dump(lock.model_dump(exclude_none=True), f)


def _get_filename_from_url(url: str, *, fallback: str | None = None) -> str:
    if fallback:
        return fallback

    name = Path(unquote(urlparse(url).path)).name
    if not name:
        name = unquote(url.rsplit("/", maxsplit=1)[-1])
    return name or "downloaded.file"


def _extract_version(name: str) -> str:
    match = re.search(r"\d+\.\d+(\.\d+)?", name)
    return match.group(0) if match else name


def _validate_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        msg = f"Unsupported URL scheme: {parsed.scheme}"
        raise ValueError(msg)

    if not parsed.netloc:
        msg = "Invalid URL: missing host"
        raise ValueError(msg)


def _download_hash_and_size(url: str) -> tuple[str, str, int]:
    sha1 = hashlib.sha1()
    sha512 = hashlib.sha512()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)

        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
                content_type = response.headers.get("Content-Type", "")

                # Reject HTML pages (common for non-direct downloads)
                if "text/html" in content_type:
                    msg = "URL does not point to a direct file download (HTML detected)"
                    raise ValueError(msg)

                downloaded = 0

                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break

                    downloaded += len(chunk)
                    if downloaded > MAX_FILE_SIZE:
                        msg = "File too large"
                        raise ValueError(msg)

                    tmp.write(chunk)
                    sha1.update(chunk)
                    sha512.update(chunk)

            size = tmp_path.stat().st_size

        finally:
            # Always clean up temp file
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)

    return sha1.hexdigest(), sha512.hexdigest(), size


def inject(
    url: str,
    client_side: Environment = "optional",
    server_side: Environment = "optional",
    inject_type: ProjectType = "mod",
    project_id: str | None = None,
) -> None:
    try:
        _validate_url(url)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from e

    path = Path.cwd()
    lock_file = path / "lock.toml"

    if not lock_file.exists():
        console.print("[red]Error:[/red] Missing lock file.")
        raise typer.Exit(code=1)

    filename = _get_filename_from_url(url)
    version = _extract_version(filename)

    console.print(f"[cyan]Downloading & hashing:[/cyan] {filename}")

    try:
        sha1, sha512, filesize = _download_hash_and_size(url)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to process file: {e}")
        raise typer.Exit(code=1) from e

    lock = load_lock(lock_file)

    # Prevent duplicate injections (by SHA1)
    for existing in lock.packages or []:
        if existing.file and existing.file.hashes and existing.file.hashes.sha1 == sha1:
            console.print("[yellow]Warning:[/yellow] File already exists in lock.")
            return

    hashes = Hashes(sha1=sha1, sha512=sha512)

    file = File(
        url=url,
        hashes=hashes,
        size=filesize,
        filename=filename,
    )

    pkg = LockPackage(
        project_id=project_id or secrets.token_hex(8),
        project_type=inject_type,
        client_side=client_side,
        server_side=server_side,
        attempts=1,
        state="resolved",
        version_number=version,
        file=file,
    )

    if lock.packages is None:
        lock.packages = []

    lock.packages.append(pkg)

    save_lock(lock_file, lock)

    console.print(f"[green]Injected successfully:[/green] {filename}")
