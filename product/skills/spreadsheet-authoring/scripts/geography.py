"""Deterministic, provenance-preserving geography taxonomy lookups."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Iterable, Mapping


class MappingStatus(str, Enum):
    EXACT = "exact"
    SOURCE_DEFINED = "source-defined"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class GeographyMapping:
    """The result of one exact, version-scoped source-label lookup."""

    status: MappingStatus
    taxonomy_id: str
    taxonomy_version: str
    source_label: str
    bucket_ids: tuple[str, ...] = ()


def stable_bucket_id(taxonomy_id: str, taxonomy_version: str, bucket_key: str) -> str:
    """Return an ID stable within, and distinct across, taxonomy versions."""
    identity = "\x1f".join((taxonomy_id, taxonomy_version, bucket_key)).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:24]
    return f"geo_{digest}"


class GeographyTaxonomy:
    """Resolve source labels without fuzzy matching or cross-taxonomy fallback.

    ``exact`` maps a source label to one canonical bucket key. ``source_defined``
    maps a report-defined label to the bucket keys explicitly supplied by that
    report. The source label is never normalized or replaced in the result.
    """

    def __init__(
        self,
        taxonomy_id: str,
        taxonomy_version: str,
        *,
        exact: Mapping[str, str] | None = None,
        source_defined: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        if not taxonomy_id or not taxonomy_version:
            raise ValueError("taxonomy_id and taxonomy_version are required")
        self.taxonomy_id = taxonomy_id
        self.taxonomy_version = taxonomy_version
        self._exact = dict(exact or {})
        self._source_defined = {
            label: tuple(bucket_keys) for label, bucket_keys in (source_defined or {}).items()
        }

    def lookup(self, source_label: str) -> GeographyMapping:
        """Resolve one label using only this taxonomy ID and version."""
        exact_key = self._exact.get(source_label)
        if exact_key is not None:
            return self._result(source_label, MappingStatus.EXACT, (exact_key,))
        source_keys = self._source_defined.get(source_label)
        if source_keys is None or not source_keys:
            return self._result(source_label, MappingStatus.UNRESOLVED)
        if len(source_keys) > 1:
            return self._result(source_label, MappingStatus.AMBIGUOUS, source_keys)
        return self._result(source_label, MappingStatus.SOURCE_DEFINED, source_keys)

    def _result(
        self,
        source_label: str,
        status: MappingStatus,
        bucket_keys: Iterable[str] = (),
    ) -> GeographyMapping:
        return GeographyMapping(
            status=status,
            taxonomy_id=self.taxonomy_id,
            taxonomy_version=self.taxonomy_version,
            source_label=source_label,
            bucket_ids=tuple(
                stable_bucket_id(self.taxonomy_id, self.taxonomy_version, key)
                for key in bucket_keys
            ),
        )
