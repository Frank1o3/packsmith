# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from httpx import AsyncClient, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RateLimitState(BaseModel):
    limit: int | None = None
    remaining: int | None = None
    reset_after: float | None = None
    last_update: float | None = None


class ModrinthClient:
    BASE_URL = "https://api.modrinth.com/v2"

    def __init__(self, user_agent: str) -> None:
        self._client = AsyncClient(
            base_url=self.BASE_URL, headers={"User-Agent": user_agent}, timeout=30.0
        )
        self.rate = RateLimitState()
        self._lock = asyncio.Lock()

    async def get(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[Any, Any]:
        async with self._lock:
            await self._respect_rate_limit()

        resp = await self._client.get(path, params=params)
        self._update_rate_limit(resp)
        resp.raise_for_status()
        logger.info(
            """Request Limit %s
\tRequest Remainder %s
\tRequest Last Update %s
\tRequest Reset After: %s""",
            self.rate.limit,
            self.rate.remaining,
            self.rate.last_update,
            self.rate.reset_after,
        )

        return resp.json()

    # ------------------------
    # rate limit logic
    # ------------------------
    def _update_rate_limit(self, resp: Response) -> None:
        headers = resp.headers

        self.rate.limit = self._safe_int(headers.get("X-Ratelimit-Limit"))
        self.rate.remaining = self._safe_int(headers.get("X-Ratelimit-Remaining"))

        reset = headers.get("X-Ratelimit-Reset")
        if reset is not None:
            self.rate.reset_after = self._safe_float(reset)
            self.rate.last_update = time.time()

    async def _respect_rate_limit(self) -> None:
        if (
            self.rate.remaining is not None
            and self.rate.remaining <= 0
            and self.rate.reset_after is not None
            and self.rate.last_update is not None
        ):
            wait_time = self.rate.reset_after - (time.time() - self.rate.last_update)
            if wait_time > 0:
                await asyncio.sleep(wait_time)

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------
    # Static methods
    # ------------------------
    @staticmethod
    def _safe_int(value: str | None) -> int | None:
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    @staticmethod
    def _safe_float(value: str | None) -> float | None:
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None
