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

DependencyRef = tuple[str, "ProjectType | None", "str | None"]


class Resolver:
    def __init__(self, manifest: Manifest, *, include_optional: bool = False) -> None:
        self.manifest = manifest
        self.include_optional = include_optional
        self.client = ModrinthClient()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        self.cache: dict[str, list[ProjectVersion]] = {}
        self.project_cache: dict[str, Hit | None] = {}
        self.version_cache: dict[str, ProjectVersion | None] = {}
        self.package_index: dict[str, LockPackage] = {}

        self.incompatibilities: dict[str, set[str]] = {}
        self.root_projects: set[str] = set()

        # Human-readable notices (e.g. conflicting version pins) collected
        # during resolution for the CLI to display.
        self.warnings: list[str] = []

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

    async def _fetch_version(self, version_id: str) -> ProjectVersion | None:
        if version_id in self.version_cache:
            return self.version_cache[version_id]

        try:
            async with self.semaphore:
                version = await self.client.get_version(version_id)
        except Exception:  # noqa: BLE001
            self.version_cache[version_id] = None
            return None

        self.version_cache[version_id] = version
        return version

    async def _display_name(self, project_id: str) -> str:
        hit = await self._fetch_project(project_id)
        if hit and hit.title:
            return hit.title
        return project_id

    async def _resolve_dependency(
        self, dep: Dependency
    ) -> tuple[str | None, str | None]:
        if dep.version_id:
            version = await self._fetch_version(dep.version_id)
            if version is None:
                return dep.project_id, None
            return version.project_id, dep.version_id

        return dep.project_id, None

    # -------------------------
    # Version selection
    # -------------------------

    @staticmethod
    def _select_version(versions: list[ProjectVersion]) -> ProjectVersion | None:
        stability_window_days = 14

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
    # Pin reconciliation
    # -------------------------

    async def _reconcile_pin(
        self, existing: LockPackage, incoming_version_id: str, *, requested_by: str
    ) -> None:
        current_id = existing.pinned_version_id

        if current_id is None:
            existing.pinned_version_id = incoming_version_id
            existing.pinned_by = requested_by
            return

        if current_id == incoming_version_id:
            return

        current_version, incoming_version = await asyncio.gather(
            self._fetch_version(current_id),
            self._fetch_version(incoming_version_id),
        )

        if current_version is None or incoming_version is None:
            # Can't compare publish dates - leave the existing pin alone
            # rather than churn state on incomplete data.
            return

        candidates = [
            (current_version, current_id, existing.pinned_by),
            (incoming_version, incoming_version_id, requested_by),
        ]
        # Stable sort: on an exact tie, keeps whichever was already in
        # effect rather than flip-flopping.
        candidates.sort(key=lambda c: c[0].published, reverse=True)
        kept_version, kept_id, kept_by = candidates[0]
        dropped_version, dropped_id, dropped_by = candidates[1]

        if kept_id == incoming_version_id:
            existing.pinned_version_id = incoming_version_id
            existing.pinned_by = requested_by
            # Force a fresh resolve against the newly-chosen pin.
            existing.state = "pending"
            existing.attempts = 0

        dep_name = await self._display_name(existing.project_id)
        kept_by_name = (
            await self._display_name(kept_by) if kept_by else "an earlier dependent"
        )
        dropped_by_name = (
            await self._display_name(dropped_by)
            if dropped_by
            else "an earlier dependent"
        )

        self.warnings.append(
            f"'{dep_name}': kept version "
            f"{kept_version.version_number or kept_id} (wanted by "
            f"'{kept_by_name}', newer) instead of version "
            f"{dropped_version.version_number or dropped_id} wanted by "
            f"'{dropped_by_name}'. If you run into problems involving "
            f"'{dep_name}', '{dropped_by_name}' expects an older version "
            f"than what's installed - that's the mod to check or remove "
            f"first."
        )

    # -------------------------
    # Dependency processing
    # -------------------------

    async def _filter_dependency_ids(
        self,
        dependencies: list[Dependency],
        current_project: str,
    ) -> list[DependencyRef]:
        dep_ids: list[DependencyRef] = []

        for dep in dependencies:
            dep_type = dep.dependency_type

            project_id, pinned_version_id = await self._resolve_dependency(dep)
            if not project_id:
                continue

            if dep_type == "incompatible":
                self._register_incompatibility(current_project, project_id)
                continue

            if dep_type == "embedded":
                continue

            if dep_type == "optional" and not self.include_optional:
                continue

            hit = await self._fetch_project(project_id)
            real_type = hit.project_type if hit else None

            dep_ids.append((project_id, real_type, pinned_version_id))

        return dep_ids

    # -------------------------
    # Package resolution
    # -------------------------

    @staticmethod
    def _populate_package_fields(
        package: LockPackage, hit: Hit, version: ProjectVersion | None
    ) -> None:
        if package.project_type is None:
            package.project_type = hit.project_type

        client_side, server_side = (version.sides if version else None) or hit.sides
        if package.client_side is None:
            package.client_side = client_side
        if package.server_side is None:
            package.server_side = server_side
        if package.version_number is None:
            package.version_number = hit.version_number

    async def _resolve_wanted_version(
        self, package: LockPackage
    ) -> ProjectVersion | None:
        if package.pinned_version_id:
            return await self._fetch_version(package.pinned_version_id)

        versions = await self._fetch_versions(package.project_id, package.project_type)
        if not versions:
            return None
        return self._select_version(versions)

    async def _resolve_package(self, package: LockPackage) -> list[DependencyRef]:
        package.attempts += 1

        if package.attempts > LIMIT_ATTEMPTS:
            package.state = "failed"
            return []

        wanted = await self._resolve_wanted_version(package)

        if wanted is None:
            package.state = "pending"
            return []

        if not wanted.files:
            package.state = "failed"
            return []

        if package.project_type == "mod":
            hit = await self._fetch_project(package.project_id)
            if hit is not None:
                self._populate_package_fields(package, hit, wanted)
        elif package.client_side is None or package.server_side is None:
            client_side, server_side = wanted.sides or ("required", "unsupported")
            if package.client_side is None:
                package.client_side = client_side
            if package.server_side is None:
                package.server_side = server_side

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

        new_packages: list[LockPackage] = []

        for pkg, dep_ids in zip(pending_packages, results, strict=False):
            for project_id, project_type, pinned_version_id in dep_ids:
                if self._is_conflict(project_id, seen):
                    if project_id in self.root_projects:
                        # root vs root conflict → mark
                        pkg.state = "conflict"
                    # dependency loses → skip
                    continue

                existing = self.package_index.get(project_id)

                if existing is not None:
                    # Don't let a dependency pin hijack something the user
                    # explicitly added themselves.
                    if pinned_version_id and project_id not in self.root_projects:
                        await self._reconcile_pin(
                            existing, pinned_version_id, requested_by=pkg.project_id
                        )
                    continue

                seen.add(project_id)

                new_pkg = LockPackage(
                    project_id=project_id,
                    project_type=project_type,
                    state="pending",
                    pinned_version_id=pinned_version_id,
                    pinned_by=pkg.project_id if pinned_version_id else None,
                )
                self.package_index[project_id] = new_pkg
                new_packages.append(new_pkg)

        return new_packages

    # -------------------------
    # Layers
    # -------------------------

    @staticmethod
    def _get_pending_packages(lock: LockFile) -> list[LockPackage]:
        return [pkg for pkg in lock.packages if pkg.state == "pending"]

    def _sync_package_index(self, lock: LockFile) -> None:
        self.package_index = {pkg.project_id: pkg for pkg in lock.packages}

    async def first_layer(self, lock: LockFile) -> None:
        self.root_projects = {pkg.project_id for pkg in lock.packages}
        self._sync_package_index(lock)

        seen = set(self.root_projects)
        pending = self._get_pending_packages(lock)

        if not pending:
            return

        new_pkgs = await self._resolve_batch(pending, seen)
        lock.packages.extend(new_pkgs)

    async def second_layer(self, lock: LockFile) -> None:
        self._sync_package_index(lock)
        seen = {pkg.project_id for pkg in lock.packages}

        while True:
            pending = self._get_pending_packages(lock)
            if not pending:
                break

            new_pkgs = await self._resolve_batch(pending, seen)
            lock.packages.extend(new_pkgs)
