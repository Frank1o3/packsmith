# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
import json
import logging
from asyncio import run
from importlib.metadata import version
from pathlib import Path
from typing import Any

from packsmith.api import ModrinthClient

USER_AGENT = (
    f"Frank1o3/packsmith/{version('packsmith')} (https://github.com/Frank1o3/packsmith)"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def dump_response(name: str, data: dict[Any, Any]) -> None:
    path = Path("debug") / f"{name}.json"
    path.parent.mkdir(exist_ok=True)

    path.write_text(json.dumps(data, indent=2))


async def async_main() -> None:
    client = ModrinthClient(USER_AGENT)
    logger.info("Testing endpoint")
    data = await client.get("/search?query=sodium&limit=20")
    dump_response("data", data)


def main() -> None:
    run(async_main())


if __name__ == "__main__":
    main()
