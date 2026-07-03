# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import asyncio
from datetime import timedelta

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

        # 🔥 NEW: conflict system
        self.incompatibilities: dict[str, set[str]] = {}
        self.root_projects: set[str] = set()

    # -------------------------
    # Fetching
    # -------------------------

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

        # 🔥 FIXED: better loader handling (helps shaders/resourcepacks)
        if project_type == "mod":
            loaders = [self.manifest.loader]
        elif project_type == "shader":
            loaders = ["iris", "optifine", "minecraft"]
        else:
            # datapack / shader / resourcepack fallback
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

    # -------------------------
    # Version selection
    # -------------------------

    @staticmethod
    def _select_version(versions: list[ProjectVersion]) -> ProjectVersion | None:
        stability_window_days = 7

        # Sort newest → oldest
        versions_sorted = sorted(versions, key=lambda v: v.published, reverse=True)

        latest = versions_sorted[0]
        window_start = latest.published - timedelta(days=stability_window_days)

        # --- Case 1: latest is RELEASE ---
        if latest.stability == Stability.RELEASE:
            return latest

        # --- Case 2: latest is BETA ---
        if latest.stability == Stability.BETA:
            return latest

        # --- Case 3: latest is ALPHA ---
        if latest.stability == Stability.ALPHA:
            # Look for BETA in window
            beta_candidates = [
                v
                for v in versions_sorted
                if v.stability == Stability.BETA and v.published >= window_start
            ]

            if beta_candidates:
                return max(beta_candidates, key=lambda v: v.published)

            # Look for RELEASE in window
            release_candidates = [
                v
                for v in versions_sorted
                if v.stability == Stability.RELEASE and v.published >= window_start
            ]

            if release_candidates:
                return max(release_candidates, key=lambda v: v.published)

            return latest

        return latest  # fallback safety

    # -------------------------
    # Conflict system
    # -------------------------

    def _register_incompatibility(self, a: str, b: str) -> None:
        self.incompatibilities.setdefault(a, set()).add(b)
        self.incompatibilities.setdefault(b, set()).add(a)

    def _is_conflict(self, project_id: str, seen: set[str]) -> bool:
        conflicts = self.incompatibilities.get(project_id, set())
        return any(p in seen for p in conflicts)

    # -------------------------
    # Dependency processing
    # -------------------------

    async def _filter_dependency_ids(
        self,
        dependencies: list[Dependency],
        current_project: str,
    ) -> list[tuple[str, ProjectType | None]]:
        dep_ids: list[tuple[str, ProjectType | None]] = []

        for dep in dependencies:
            dep_type = dep.dependency_type

            project_id = await self._resolve_dependency_project_id(dep)
            if not project_id:
                continue

            # 🔥 Register incompatibilities
            if dep_type == "incompatible":
                self._register_incompatibility(current_project, project_id)
                continue

            if dep_type == "embedded":
                continue

            if dep_type == "optional" and not self.include_optional:
                continue

            hit = await self._fetch_project(project_id)
            real_type = hit.project_type if hit else None

            dep_ids.append((project_id, real_type))

        return dep_ids

    # -------------------------
    # Package resolution
    # -------------------------

    @staticmethod
    def _populate_package_fields(package: LockPackage, hit: Hit) -> None:
        if package.project_type is None:
            package.project_type = hit.project_type
        if package.client_side is None:
            package.client_side = hit.client_side
        if package.server_side is None:
            package.server_side = hit.server_side
        if package.version_number is None:
            package.version_number = hit.version_number

    async def _resolve_package(
        self, package: LockPackage
    ) -> list[tuple[str, ProjectType | None]]:
        versions = await self._fetch_versions(package.project_id, package.project_type)
        package.attempts += 1

        if package.attempts > LIMIT_ATTEMPTS:
            package.state = "failed"
            return []

        if versions is None:
            package.state = "pending"
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
        if not wanted or not wanted.files:
            package.state = "failed"
            return []

        package.file = wanted.files[0]
        package.state = "resolved"
        package.version_number = wanted.version_number

        return await self._filter_dependency_ids(
            wanted.dependencies,
            package.project_id,
        )

    # -------------------------
    # Batch resolution
    # -------------------------

    async def _resolve_batch(
        self, pending_packages: list[LockPackage], seen: set[str]
    ) -> list[LockPackage]:
        tasks = [self._resolve_package(pkg) for pkg in pending_packages]
        results = await asyncio.gather(*tasks)

        new_packages = []

        for pkg, dep_ids in zip(pending_packages, results, strict=False):
            for project_id, project_type in dep_ids:
                if project_id in seen:
                    continue

                # 🔥 Conflict handling
                if self._is_conflict(project_id, seen):
                    if project_id in self.root_projects:
                        # root vs root conflict → mark
                        pkg.state = "conflict"
                    # dependency loses → skip
                    continue

                seen.add(project_id)

                new_packages.append(
                    LockPackage(
                        project_id=project_id,
                        project_type=project_type,
                        state="pending",
                    )
                )

        return new_packages

    # -------------------------
    # Layers
    # -------------------------

    @staticmethod
    def _get_pending_packages(lock: LockFile) -> list[LockPackage]:
        return [pkg for pkg in lock.packages if pkg.state == "pending"]

    async def first_layer(self, lock: LockFile) -> None:
        # 🔥 Initialize root projects
        self.root_projects = {pkg.project_id for pkg in lock.packages}

        seen = set(self.root_projects)
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
