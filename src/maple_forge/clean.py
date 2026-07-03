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


def _source_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame:
        return frame[name]
    return pd.Series(pd.NA, index=frame.index, dtype="object")


def _clean_text_column(frame: pd.DataFrame, name: str) -> pd.Series:
    text = (
        _source_column(frame, name)
        .astype("string")
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    return text.mask(text == "")


def _first_text_column(frame: pd.DataFrame, *names: str) -> pd.Series:
    candidates = pd.concat(
        [_clean_text_column(frame, name) for name in names],
        axis=1,
    )
    return candidates.bfill(axis=1).iloc[:, 0]


def _money_column(frame: pd.DataFrame, name: str) -> pd.Series:
    text = _clean_text_column(frame, name)
    negative = text.str.match(r"^\(.*\)$", na=False)
    cleaned = text.str.strip("()").str.replace(r"[^0-9.+-]", "", regex=True)
    values = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    return values.mask(negative, -values.abs())


def _date_column(frame: pd.DataFrame, name: str) -> pd.Series:
    parsed = pd.to_datetime(
        _clean_text_column(frame, name),
        errors="coerce",
        format="mixed",
    )
    return parsed.dt.strftime("%Y-%m-%d")


def _province_column(frame: pd.DataFrame) -> pd.Series:
    text = _clean_text_column(frame, "recipient_province")
    upper = text.str.upper()
    mapped = text.str.casefold().map(PROVINCE_CODES)
    return upper.where(upper.isin(VALID_PROVINCE_CODES), mapped)


def _department_column(frame: pd.DataFrame) -> pd.Series:
    title = _clean_text_column(frame, "owner_org_title")
    english_title = title.str.split(" | ", n=1, regex=False).str[0]
    return english_title.fillna(_clean_text_column(frame, "owner_org"))


def _record_id_column(frame: pd.DataFrame) -> pd.Series:
    reference = _clean_text_column(frame, "ref_number")
    amendment = _clean_text_column(frame, "amendment_number").fillna("0")
    primary_identity = "goc-grants:" + reference + ":" + amendment

    fallback_identity = (
        "goc-grants:fallback:"
        + _first_text_column(
            frame,
            "recipient_legal_name",
            "recipient_operating_name",
            "research_organization_name",
        ).fillna("")
        + "\x1f"
        + _first_text_column(
            frame,
            "agreement_title_en",
            "agreement_title_fr",
        ).fillna("")
        + "\x1f"
        + _clean_text_column(frame, "agreement_value").fillna("")
        + "\x1f"
        + _date_column(frame, "agreement_start_date").fillna("")
        + "\x1f"
        + _clean_text_column(frame, "owner_org").fillna("")
    )
    identity = primary_identity.where(reference.notna(), fallback_identity)
    return identity.map(
        lambda value: (
            f"grant_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"
        )
    )


def clean_chunk(
    frame: pd.DataFrame,
    *,
    source_url: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    """Normalize and map a CSV chunk into canonical records."""
    normalized = normalize_columns(frame)
    records = pd.DataFrame(
        {
            "record_id": _record_id_column(normalized),
            "recipient_name": _first_text_column(
                normalized,
                "recipient_legal_name",
                "recipient_operating_name",
                "research_organization_name",
            ),
            "agreement_title": _first_text_column(
                normalized,
                "agreement_title_en",
                "agreement_title_fr",
                "agreement_number",
            ),
            "agreement_value": _money_column(normalized, "agreement_value"),
            "agreement_start_date": _date_column(
                normalized,
                "agreement_start_date",
            ),
            "agreement_end_date": _date_column(normalized, "agreement_end_date"),
            "province": _province_column(normalized),
            "city": _clean_text_column(normalized, "recipient_city"),
            "department": _department_column(normalized),
            "program_name": _first_text_column(
                normalized,
                "prog_name_en",
                "prog_name_fr",
            ),
            "description": _first_text_column(
                normalized,
                "description_en",
                "description_fr",
            ),
            "source_url": source_url,
            "retrieved_at": retrieved_at,
        },
        index=normalized.index,
    )
    ordered = records.loc[:, CANONICAL_FIELDS].astype(object)
    return ordered.where(pd.notna(ordered), None).to_dict(orient="records")
