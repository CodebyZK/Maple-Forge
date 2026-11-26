"""Validate normalized Maple Forge records."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Integral
from typing import Any

from maple_forge.config import CANONICAL_FIELDS, REQUIRED_FIELDS


@dataclass(frozen=True)
class RejectedRecord:
    """A canonical record and the validation errors that rejected it."""

    record: dict[str, Any]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ValidationResult:
    """Accepted and rejected results for a batch of canonical records."""

    accepted: list[dict[str, Any]]
    rejected: list[RejectedRecord]


def _is_iso_date(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10


def _is_utc_datetime(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_record(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return validation errors for one canonical record."""
    errors: list[str] = []
    missing_columns = [field for field in CANONICAL_FIELDS if field not in record]
    if missing_columns:
        errors.append(f"missing canonical fields: {', '.join(missing_columns)}")

    for field in REQUIRED_FIELDS:
        value = record.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"{field} is required")

    value = record.get("agreement_value")
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        errors.append("agreement_value must be a finite number")

    amendment = record.get("amendment_number")
    if amendment is not None and (
        isinstance(amendment, bool)
        or not isinstance(amendment, Integral)
        or amendment < 0
    ):
        errors.append("amendment_number must be a non-negative integer")

    errors.extend(
        f"{field} must be an ISO 8601 date or null"
        for field in ("agreement_start_date", "agreement_end_date")
        if not _is_iso_date(record.get(field))
    )

    if record.get("retrieved_at") is not None and not _is_utc_datetime(
        record.get("retrieved_at")
    ):
        errors.append("retrieved_at must be an ISO 8601 UTC datetime ending in Z")

    return tuple(errors)


def validate_records(records: Iterable[Mapping[str, Any]]) -> ValidationResult:
    """Partition canonical records into accepted and rejected collections."""
    accepted: list[dict[str, Any]] = []
    rejected: list[RejectedRecord] = []
    for source_record in records:
        record = dict(source_record)
        errors = validate_record(record)
        if errors:
            rejected.append(RejectedRecord(record=record, errors=errors))
        else:
            accepted.append(record)
    return ValidationResult(accepted=accepted, rejected=rejected)
