"""Clean and normalize grants source data."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime
from typing import Any

import pandas as pd

from maple_forge.config import CANONICAL_FIELDS

_NON_WORDS = re.compile(r"[^a-z0-9]+")

PROVINCE_CODES = {
    "alberta": "AB",
    "british columbia": "BC",
    "manitoba": "MB",
    "new brunswick": "NB",
    "newfoundland and labrador": "NL",
    "newfoundland & labrador": "NL",
    "northwest territories": "NT",
    "nova scotia": "NS",
    "nunavut": "NU",
    "ontario": "ON",
    "prince edward island": "PE",
    "quebec": "QC",
    "québec": "QC",
    "saskatchewan": "SK",
    "yukon": "YT",
}
VALID_PROVINCE_CODES = frozenset(PROVINCE_CODES.values())


def normalize_column_name(name: object) -> str:
    """Convert a source column label to lowercase snake_case."""
    normalized = _NON_WORDS.sub("_", str(name).strip().lower())
    return normalized.strip("_")


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with normalized source column labels."""
    normalized = frame.copy()
    normalized.columns = [normalize_column_name(column) for column in frame.columns]
    return normalized


def clean_text(value: Any) -> str | None:
    """Trim published text and normalize runs of whitespace."""
    if value is None or pd.isna(value):
        return None
    text = " ".join(str(value).split())
    return text or None


def first_text(row: pd.Series, *columns: str) -> str | None:
    """Return the first non-empty text value from candidate columns."""
    for column in columns:
        value = clean_text(row.get(column))
        if value is not None:
            return value
    return None


def parse_money(value: Any) -> float | None:
    """Parse a Canadian monetary value, returning None for invalid values."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.+-]", "", text.strip("()"))
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if negative:
        number = -number
    return number if math.isfinite(number) else None


def parse_date(value: Any) -> str | None:
    """Parse a date into ISO 8601 YYYY-MM-DD format."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = pd.to_datetime(str(value).strip(), errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def normalize_province(value: Any) -> str | None:
    """Normalize Canadian province and territory values to postal codes."""
    text = clean_text(value)
    if text is None:
        return None
    upper = text.upper()
    if upper in VALID_PROVINCE_CODES:
        return upper
    return PROVINCE_CODES.get(text.casefold())


def department_name(value: Any, fallback: Any = None) -> str | None:
    """Return the English institution title from the bilingual source label."""
    text = clean_text(value)
    if text:
        return clean_text(text.split(" | ", maxsplit=1)[0])
    return clean_text(fallback)


def stable_record_id(row: pd.Series) -> str:
    """Build a stable ID from the source reference and amendment identifiers."""
    reference = clean_text(row.get("ref_number"))
    amendment = clean_text(row.get("amendment_number")) or "0"
    if reference:
        identity = f"goc-grants:{reference}:{amendment}"
    else:
        fallback_values = (
            first_text(
                row,
                "recipient_legal_name",
                "recipient_operating_name",
                "research_organization_name",
            ),
            first_text(row, "agreement_title_en", "agreement_title_fr"),
            clean_text(row.get("agreement_value")),
            parse_date(row.get("agreement_start_date")),
            clean_text(row.get("owner_org")),
        )
        identity = "goc-grants:fallback:" + "\x1f".join(
            value or "" for value in fallback_values
        )
    return f"grant_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def clean_record(
    row: pd.Series,
    *,
    source_url: str,
    retrieved_at: str,
) -> dict[str, Any]:
    """Map one normalized source row into the Maple Forge schema."""
    record = {
        "record_id": stable_record_id(row),
        "recipient_name": first_text(
            row,
            "recipient_legal_name",
            "recipient_operating_name",
            "research_organization_name",
        ),
        "agreement_title": first_text(
            row,
            "agreement_title_en",
            "agreement_title_fr",
            "agreement_number",
        ),
        "agreement_value": parse_money(row.get("agreement_value")),
        "agreement_start_date": parse_date(row.get("agreement_start_date")),
        "agreement_end_date": parse_date(row.get("agreement_end_date")),
        "province": normalize_province(row.get("recipient_province")),
        "city": clean_text(row.get("recipient_city")),
        "department": department_name(
            row.get("owner_org_title"),
            row.get("owner_org"),
        ),
        "program_name": first_text(row, "prog_name_en", "prog_name_fr"),
        "description": first_text(row, "description_en", "description_fr"),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    return {field: record[field] for field in CANONICAL_FIELDS}


def clean_chunk(
    frame: pd.DataFrame,
    *,
    source_url: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    """Normalize and map a CSV chunk into canonical records."""
    normalized = normalize_columns(frame)
    return [
        clean_record(row, source_url=source_url, retrieved_at=retrieved_at)
        for _, row in normalized.iterrows()
    ]
