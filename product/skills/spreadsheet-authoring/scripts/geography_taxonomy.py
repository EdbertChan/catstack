"""Deterministic geography taxonomy resolution for spreadsheet observations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

STATUSES = {"exact", "source_defined", "ambiguous", "unresolved"}


def _key(value: str) -> str:
    return " ".join(value.strip().casefold().split())


@dataclass(frozen=True)
class GeographyMapping:
    taxonomy_id: str
    taxonomy_version: str
    source_label: str
    status: str
    canonical_code: str = ""
    included_areas: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unsupported geography mapping status: {self.status}")

    @property
    def lookup_key(self) -> tuple[str, str, str]:
        return (_key(self.taxonomy_id), _key(self.taxonomy_version), _key(self.source_label))

    @property
    def bucket_id(self) -> str:
        identity = "|".join(self.lookup_key + (_key(self.canonical_code),))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"{self.taxonomy_id}:{self.taxonomy_version}:{digest}"


class GeographyRegistry:
    def __init__(self, mappings: tuple[GeographyMapping, ...] = ()) -> None:
        by_key: dict[tuple[str, str, str], GeographyMapping] = {}
        for mapping in mappings:
            if mapping.lookup_key in by_key:
                raise ValueError(f"duplicate geography mapping: {mapping.lookup_key}")
            by_key[mapping.lookup_key] = mapping
        self._mappings = by_key

    def resolve(self, taxonomy_id: str, taxonomy_version: str, source_label: str) -> GeographyMapping:
        mapping = self._mappings.get((_key(taxonomy_id), _key(taxonomy_version), _key(source_label)))
        if mapping is not None:
            return mapping
        return GeographyMapping(taxonomy_id, taxonomy_version, source_label, "unresolved")
