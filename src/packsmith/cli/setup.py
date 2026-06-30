# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT


from pathlib import Path

from packsmith.core.models import Manifest


def setup(pack_name: str, game_version: str, loader: str, loader_version: str) -> None:
    path = Path.cwd() / pack_name
    register_file = path / "meta.json"
    lock_file = path / "lock.toml"
    dirs = [
        "mods",
        "overrides/config",
        "overrides/resourcepacks",
        "overrides/shaderpacks",
    ]
    path.mkdir(parents=True, exist_ok=True)

    for directory in dirs:
        (path / directory).mkdir(parents=True, exist_ok=True)

    register_file.touch(exist_ok=True)
    lock_file.touch(exist_ok=True)
    register_file.write_text(
        Manifest(
            name=pack_name,
            game_version=game_version,
            loader=loader,
            loader_version=loader_version,
            mods=[],
            resourcepacks=[],
            shaderpacks=[],
        ).model_dump_json(indent=2)
    )
