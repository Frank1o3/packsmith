# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import asyncio

from packsmith.api import ModrinthClient
from packsmith.core.models import (
    Dependency,
    Hit,
    LockFile,
    LockPackage,
    Manifest,
    ProjectVersion,
)

MAX_CONCURRENT_REQUESTS = 5


class Resolver:
    """Asynchronous dependency resolver for Modrinth-based modpacks."""

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
            self.project_cache[project_id] = None
            return None

        self.project_cache[project_id] = hit
        return hit

    def _select_version(self, versions: list[ProjectVersion]) -> ProjectVersion | None:
        """Select the best compatible version based on stability and date.

        Returns:
            The best matching ProjectVersion, or None if no compatible version exists.

        """
        game_version = self.manifest.game_version
        loader = self.manifest.loader

        compatible = [
            v
            for v in versions
            if game_version in v.game_versions and loader in v.loaders
        ]
        if not compatible:
            return None

        # max by stability descending, then date descending
        return max(compatible, key=lambda v: (v.stability, v.published))

    async def _fetch_versions(self, project_id: str) -> list[ProjectVersion] | None:
        """Fetch versions from API or cache, handling exceptions.

        Returns:
            A list of ProjectVersion objects, or None if the fetch fails.

        """
        if project_id in self.cache:
            return self.cache[project_id]

        try:
            async with self.semaphore:
                versions = await self.client.get_project_versions(project_id)
            self.cache[project_id] = versions
        except Exception:  # noqa: BLE001
            # TODO: Integrate with project's logging framework to log the exception
            self.cache[project_id] = []
            return None

        return versions

    @staticmethod
    def _populate_package_fields(package: LockPackage, hit: Hit) -> None:
        if package.project_type is None:
            package.project_type = hit.project_type
        if package.client_side is None:
            package.client_side = hit.client_side
        if package.server_side is None:
            package.server_side = hit.server_side

    def _filter_dependency_ids(self, dependencies: list[Dependency]) -> list[str]:
        dep_ids: list[str] = []
        for dep in dependencies:
            if not dep.project_id:
                continue

            dep_type = dep.dependency_type
            if dep_type in {"embedded", "incompatible"}:
                continue
            if dep_type == "optional" and not self.include_optional:
                continue

            dep_ids.append(dep.project_id)

        return dep_ids

    async def _resolve_package(self, package: LockPackage) -> list[str]:
        """Resolve a single package and return discovered dependency IDs.

        Returns:
            A list of project IDs for newly discovered dependencies.

        """
        versions = await self._fetch_versions(package.project_id)
        if not versions:
            package.state = "failed"
            return []

        hit = await self._fetch_project(package.project_id)
        if hit is not None:
            self._populate_package_fields(package, hit)

        wanted = self._select_version(versions)
        if not wanted:
            package.state = "failed"
            return []

        if not wanted.files:
            package.state = "failed"
            return []

        package.file = wanted.files[0]
        package.state = "resolved"

        return self._filter_dependency_ids(wanted.dependencies)

    async def _resolve_batch(
        self, pending_packages: list[LockPackage], seen: set[str]
    ) -> list[LockPackage]:
        """Resolve a batch of packages concurrently and return new pending packages.

        Returns:
            A list of newly created pending LockPackage objects.

        """
        tasks = [self._resolve_package(pkg) for pkg in pending_packages]
        results = await asyncio.gather(*tasks)

        new_packages = []
        for dep_ids in results:
            for project_id in dep_ids:
                # O(1) membership check to prevent duplicates
                if project_id not in seen:
                    seen.add(project_id)
                    new_packages.append(
                        LockPackage(project_id=project_id, state="pending")
                    )

        return new_packages

    @staticmethod
    def _get_pending_packages(lock: LockFile) -> list[LockPackage]:
        """Return a list of packages that are still pending resolution.

        Returns:
            A list of pending packages.

        """
        return [pkg for pkg in lock.packages if pkg.state == "pending"]

    async def first_layer(self, lock: LockFile) -> None:
        """Resolve the initial packages in the lock file and
        discover their dependencies.
        """
        seen = {pkg.project_id for pkg in lock.packages}
        pending = self._get_pending_packages(lock)

        if not pending:
            return

        new_pkgs = await self._resolve_batch(pending, seen)
        lock.packages.extend(new_pkgs)

    async def second_layer(self, lock: LockFile) -> None:
        """Resolve the remaining pending packages
        until the dependency graph is complete.
        This acts as a fixpoint algorithm,
        repeating until no pending packages remain.
        """
        seen = {pkg.project_id for pkg in lock.packages}

        while True:
            pending = self._get_pending_packages(lock)
            if not pending:
                break

            new_pkgs = await self._resolve_batch(pending, seen)
            lock.packages.extend(new_pkgs)
