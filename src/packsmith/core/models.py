# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT
import re
from difflib import SequenceMatcher
from operator import attrgetter
from typing import Literal

from pydantic import BaseModel, ConfigDict

MATCH_EXACT = 100
MATCH_ACRONYM = 90
MATCH_PREFIX = 70
MATCH_CONTAINS = 50
MATCH_FUZZY = 30
FUZZY_THRESHOLD = 0.8
_NORMALIZE_RE = re.compile(r"[\s\-_]+")

ProjectType = Literal[
    "mod",
    "modpack",
    "resourcepack",
    "shader",
    "datapack",
]


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub("", text.casefold())


def _acronym(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.casefold())
    return "".join(word[0] for word in words if word)


class BaseAPIModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Hit(BaseAPIModel):
    project_id: str
    project_type: ProjectType
    slug: str
    title: str

    client_side: Literal["unsupported", "required", "optional"]
    server_side: Literal["unsupported", "required", "optional"]


class MatchResult(BaseModel):
    hit: Hit
    score: int = MATCH_EXACT

    @property
    def exact(self) -> bool:
        return self.score == MATCH_EXACT


class Search(BaseAPIModel):
    hits: list[Hit]
    total_hits: int

    @property
    def found(self) -> bool:
        return self.total_hits > 0

    def match(
        self,
        name: str,
        project_type: ProjectType,
    ) -> list[MatchResult]:
        target = _normalize(name)
        acronym = _acronym(name)

        matches: list[MatchResult] = []

        for hit in self.hits:
            if hit.project_type != project_type:
                continue

            title = _normalize(hit.title)
            slug = _normalize(hit.slug)

            score = 0

            # Perfect match
            if target in {title, slug}:
                score = MATCH_EXACT

            # Acronym (Entity Model Features -> emf)
            elif acronym and (acronym in {title, slug}):
                score = MATCH_ACRONYM

            # Prefix match (Continuity -> Continuity Reborn)
            elif title.startswith(target) or slug.startswith(target):
                score = MATCH_PREFIX

            # Contains match (Sodium -> Sodium Extras)
            elif target in title or target in slug:
                score = MATCH_CONTAINS

            elif (
                max(
                    SequenceMatcher(None, target, title).ratio(),
                    SequenceMatcher(None, target, slug).ratio(),
                )
                >= FUZZY_THRESHOLD
            ):
                score = MATCH_FUZZY

            if score:
                matches.append(MatchResult(hit=hit, score=score))

        matches.sort(key=attrgetter("score"), reverse=True)
        return matches
