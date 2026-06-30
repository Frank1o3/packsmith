# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
import re
from difflib import SequenceMatcher
from enum import IntEnum
from operator import attrgetter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

FUZZY_THRESHOLD = 0.80
ERROR_NOT_IN_PACK = "Command must be ran in the modpack directory"
_NORMALIZE_RE = re.compile(r"[\s\-_]+")
_STABILITY = {
    "release": 3,
    "beta": 2,
    "alpha": 1,
}

ProjectType = Literal[
    "mod",
    "modpack",
    "resourcepack",
    "shader",
    "datapack",
]
Environment = Literal[
    "unsupported",
    "optional",
    "required",
]
DependencyType = Literal[
    "required",
    "optional",
    "incompatible",
    "embedded",
]
VersionType = Literal[
    "release",
    "beta",
    "alpha",
]
PROJECT_TYPE_TO_FIELD = {
    "mod": "mods",
    "resourcepack": "resourcepacks",
    "shader": "shaderpacks",
}


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub("", text.casefold())


def _acronym(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.casefold())
    return "".join(word[0] for word in words if word)


class MatchScore(IntEnum):
    EXACT = 100
    ACRONYM = 90
    PREFIX = 70
    CONTAINS = 50
    FUZZY = 30
    NOTHING = 0


class BaseAPIModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Hit(BaseAPIModel):
    project_id: str = ""
    project_type: ProjectType = "mod"
    slug: str = ""
    title: str = ""

    client_side: Environment = "unsupported"
    server_side: Environment = "unsupported"

    @property
    def normalized_title(self) -> str:
        return _normalize(self.title)

    @property
    def normalized_slug(self) -> str:
        return _normalize(self.slug)


class MatchResult(BaseModel):
    hit: Hit
    score: int = MatchScore.EXACT


class MatchResults(BaseModel):
    results: list[MatchResult] = Field(default_factory=list)

    @property
    def best(self) -> MatchResult | None:
        return self.results[0] if self.results else None


class Search(BaseAPIModel):
    hits: list[Hit] = Field(default_factory=list)
    total_hits: int

    @property
    def found(self) -> bool:
        return self.total_hits > 0

    def match(
        self,
        name: str,
        project_type: ProjectType,
    ) -> MatchResults:
        if not self.found:
            return MatchResults(
                results=[
                    MatchResult(
                        hit=Hit(),
                        score=MatchScore.NOTHING,
                    )
                ]
            )
        target = _normalize(name)
        acronym = _acronym(name)

        matches: list[MatchResult] = []

        for hit in self.hits:
            if hit.project_type != project_type:
                continue

            title = hit.normalized_title
            slug = hit.normalized_slug

            score = 0

            # Perfect match
            if target == title or target == slug:  # noqa: PLR1714, SIM109
                score = MatchScore.EXACT

            # Acronym (Entity Model Features -> emf)
            elif acronym == title or acronym == slug:  # noqa: PLR1714, SIM109
                score = MatchScore.ACRONYM

            # Prefix match (Continuity -> Continuity Reborn)
            elif title.startswith(target) or slug.startswith(target):
                score = MatchScore.PREFIX

            # Contains match (Sodium -> Sodium Extras)
            elif target in title or target in slug:
                score = MatchScore.CONTAINS

            elif (
                max(
                    SequenceMatcher(None, target, title).ratio(),
                    SequenceMatcher(None, target, slug).ratio(),
                )
                >= FUZZY_THRESHOLD
            ):
                score = MatchScore.FUZZY

            if score:
                matches.append(MatchResult(hit=hit, score=score))

        matches.sort(key=attrgetter("score"), reverse=True)
        return MatchResults(results=matches)


class Dependency(BaseAPIModel):
    project_id: str | None = None
    dependency_type: DependencyType


class Hashes(BaseAPIModel):
    sha1: str
    sha512: str


class File(BaseAPIModel):
    url: str
    hashes: Hashes
    size: int


class ProjectVersion(BaseAPIModel):
    game_versions: list[str] = Field(default_factory=list)
    loaders: list[str] = Field(default_factory=list)
    version_type: VersionType
    files: list[File] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)

    @property
    def is_release(self) -> bool:
        return self.version_type == "release"

    @property
    def is_beta(self) -> bool:
        return self.version_type == "beta"

    @property
    def is_alpha(self) -> bool:
        return self.version_type == "alpha"

    @property
    def stability(self) -> int:
        return _STABILITY[self.version_type]


ProjectVersions = TypeAdapter(list[ProjectVersion])


# Meta.json file used for storing the pack data
class Manifest(BaseAPIModel):
    name: str
    game_version: str
    loader: str
    loader_version: str
    mods: list[str] = Field(default_factory=list)
    resourcepacks: list[str] = Field(default_factory=list)
    shaderpacks: list[str] = Field(default_factory=list)


class Env(BaseAPIModel):
    client: Environment
    server: Environment


class ModPackFile(BaseAPIModel):
    path: str
    hashes: Hashes
    env: Env
    downloads: list[str] = Field(default_factory=list)
    fileSize: int  # noqa: N815


class ModPack(BaseAPIModel):
    formatVersion: int = 1  # noqa: N815
    game: str = "minecraft"
    versionId: str  # noqa: N815
    name: str
    files: list[ModPackFile] = Field(default_factory=list)
    dependencies: dict[str, str] = Field(default_factory=dict)


class LockPackage(BaseModel):
    name: str
    project_id: str
    project_type: ProjectType
    url: str | None = None


class LockFile(BaseModel):
    package: list[LockPackage] = Field(default_factory=list)
