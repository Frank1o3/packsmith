# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import asyncio
from datetime import UTC, datetime, timedelta

from packsmith.api import ModrinthClient
from packsmith.core.models import (
    Dependency,
    Hit,
    LockFile,
    LockPackage,
    Manifest,
    ProjectType,
    ProjectVersion,
    Stability,
)

MAX_CONCURRENT_REQUESTS = 5
LIMIT_ATTEMPTS = 3


class Resolver:
    def __init__(self, manifest: Manifest, *, include_optional: bool = False) -> None:
        self.manifest = manifest
        self.include_optional = include_optional
        self.client = ModrinthClient()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.cache: dict[str, list[ProjectVersion]] = {}
        self.project_cache: dict[str, Hit | None] = {}

    async def _fetch_project(self, project_id: str) -> Hit | None:
        if project_id in self.project_cache:
            return self.project_cache[project_id]

        try:
            async with self.semaphore:
                hit = await self.client.get_project(project_id)
        except Exception:  # noqa: BLE001
            return None

        self.project_cache[project_id] = hit
        return hit

    async def _fetch_versions(
        self, project_id: str, project_type: ProjectType | None
    ) -> list[ProjectVersion] | None:
        if project_id in self.cache:
            return self.cache[project_id]

        if project_type == "mod":
            loaders = [self.manifest.loader]
        elif project_type is None:
            loaders = ["minecraft", self.manifest.loader]  # fallback
        else:
            loaders = ["minecraft", self.manifest.loader]

        try:
            async with self.semaphore:
                versions = await self.client.get_project_versions(
                    project_id,
                    loaders=loaders,
                    game_versions=[self.manifest.game_version],
                )
        except Exception:  # noqa: BLE001
            return None

        self.cache[project_id] = versions
        return versions

    async def _resolve_dependency_project_id(self, dep: Dependency) -> str | None:
        if dep.project_id:
            return dep.project_id

        if dep.version_id:
            try:
                async with self.semaphore:
                    version = await self.client.get_version(dep.version_id)
            except Exception:  # noqa: BLE001
                return None
            else:
                return version.project_id

        return None

    @staticmethod
    def _select_version(versions: list[ProjectVersion]) -> ProjectVersion | None:
        if not versions:
            return None

        now = datetime.now(UTC)
        cutoff = now - timedelta(days=90)

        stable_versions = [v for v in versions if v.stability >= Stability.BETA]

        if stable_versions:
            best_stable = max(
                stable_versions,
                key=lambda v: (v.stability, v.published, v.downloads),
            )

            if best_stable.published >= cutoff:
                return best_stable

        # fallback: allow anything
        return max(
            versions,
            key=lambda v: (v.stability, v.downloads, v.published),
        )

    @staticmethod
    def _populate_package_fields(package: LockPackage, hit: Hit) -> None:
        if package.project_type is None:
            package.project_type = hit.project_type
        if package.client_side is None:
            package.client_side = hit.client_side
        if package.server_side is None:
            package.server_side = hit.server_side

    async def _filter_dependency_ids(
        self, dependencies: list[Dependency]
    ) -> list[tuple[str, ProjectType | None]]:
        dep_ids: list[tuple[str, ProjectType | None]] = []

        for dep in dependencies:
            dep_type = dep.dependency_type

            if dep_type in {"embedded", "incompatible"}:
                continue
            if dep_type == "optional" and not self.include_optional:
                continue

            project_id = await self._resolve_dependency_project_id(dep)
            if not project_id:
                continue

            hit = await self._fetch_project(project_id)

            real_type = hit.project_type if hit else None

            dep_ids.append((project_id, real_type))

        return dep_ids

    async def _resolve_package(
        self, package: LockPackage
    ) -> list[tuple[str, ProjectType | None]]:
        versions = await self._fetch_versions(package.project_id, package.project_type)
        package.attempts += 1

        if package.attempts > LIMIT_ATTEMPTS:
            package.state = "failed"
            return []

        if versions is None:
            package.state = "pending"  # retry later
            return []

        if not versions:
            package.state = "failed"
            return []

        if package.project_type == "mod":
            hit = await self._fetch_project(package.project_id)
            if hit is not None:
                self._populate_package_fields(package, hit)
        else:
            if package.client_side is None:
                package.client_side = "required"
            if package.server_side is None:
                package.server_side = "unsupported"

        wanted = self._select_version(versions)
        if not wanted:
            package.state = "failed"
            return []

        if not wanted.files:
            package.state = "failed"
            return []

        package.file = wanted.files[0]
        package.state = "resolved"

        return await self._filter_dependency_ids(wanted.dependencies)

    async def _resolve_batch(
        self, pending_packages: list[LockPackage], seen: set[str]
    ) -> list[LockPackage]:
        tasks = [self._resolve_package(pkg) for pkg in pending_packages]
        results = await asyncio.gather(*tasks)

        new_packages = []
        for dep_ids in results:
            for project_id, project_type in dep_ids:
                if project_id not in seen:
                    seen.add(project_id)
                    new_packages.append(
                        LockPackage(
                            project_id=project_id,
                            project_type=project_type,
                            state="pending",
                        )
                    )

        return new_packages

    @staticmethod
    def _get_pending_packages(lock: LockFile) -> list[LockPackage]:
        return [pkg for pkg in lock.packages if pkg.state == "pending"]

    async def first_layer(self, lock: LockFile) -> None:
        seen = {pkg.project_id for pkg in lock.packages}
        pending = self._get_pending_packages(lock)

        if not pending:
            return

        new_pkgs = await self._resolve_batch(pending, seen)
        lock.packages.extend(new_pkgs)

    async def second_layer(self, lock: LockFile) -> None:
        seen = {pkg.project_id for pkg in lock.packages}

        while True:
            pending = self._get_pending_packages(lock)
            if not pending:
                break

            new_pkgs = await self._resolve_batch(pending, seen)
            lock.packages.extend(new_pkgs)
