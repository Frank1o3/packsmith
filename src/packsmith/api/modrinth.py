# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

from httpx import AsyncClient, QueryParams, Response
from pydantic import BaseModel

from packsmith.core.models import Hit, ProjectVersion, ProjectVersions, Search

if TYPE_CHECKING:
    from packsmith.core.models import ProjectType

PrimitiveData = str | int | float | bool | None

QueryParamTypes = (
    QueryParams
    | Mapping[str, PrimitiveData | Sequence[PrimitiveData]]
    | list[tuple[str, PrimitiveData]]
    | tuple[tuple[str, PrimitiveData], ...]
    | str
    | bytes
) | None

logger = logging.getLogger(__name__)


class RateLimitState(BaseModel):
    limit: int | None = None
    remaining: int | None = None
    reset_after: float | None = None
    last_update: float | None = None


class ModrinthClient:
    BASE_URL = "https://api.modrinth.com/v2"

    def __init__(self) -> None:
        user_agent = f"Frank1o3/packsmith/{version('packsmith')} (https://github.com/Frank1o3/packsmith)"

        self._client = AsyncClient(
            base_url=self.BASE_URL, headers={"User-Agent": user_agent}, timeout=30.0
        )
        self.rate = RateLimitState()
        self._lock = asyncio.Lock()

    async def get(
        self,
        path: str,
        *,
        params: QueryParamTypes = None,
    ) -> Any:
        async with self._lock:
            await self._respect_rate_limit()

        resp = await self._client.get(path, params=params)
        self._update_rate_limit(resp)
        resp.raise_for_status()

        return resp.json()

    async def search(
        self, name: str, project_type: ProjectType, loader: str, game_version: str
    ) -> Search:
        facets = [
            [f"project_type:{project_type}"],
            [f"versions:{game_version}"],
        ]
        params = {
            "query": name,
            "limit": 15,
            "facets": json.dumps(facets),
        }
        if project_type == "mod":
            facets.append([f"categories:{loader}"])
        return Search.model_validate(await self.get("/search", params=params))

    async def get_project(self, project_id: str) -> Hit:
        endpoint = f"/project/{project_id}/"
        return Hit.model_validate_json(await self.get(endpoint))

    async def get_project_versions(self, project_id: str) -> list[ProjectVersion]:
        endpoint = f"/project/{project_id}/version"
        return ProjectVersions.validate_python(await self.get(endpoint))

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

    async def __aexit__(self, *_: object) -> None:
        await self.close()

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
