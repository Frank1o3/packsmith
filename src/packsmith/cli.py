# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def main() -> None:
    logger.info("Hello from packsmith!")


if __name__ == "__main__":
    main()
