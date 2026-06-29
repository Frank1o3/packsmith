# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
import logging
from importlib.metadata import version

USER_AGENT = (
    f"Frank1o3/packsmith/{version('packsmith')} (https://github.com/Frank1o3/packsmith)"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Hello from packsmith!")


if __name__ == "__main__":
    main()
