"""Clean and normalize grants source data."""

from __future__ import annotations

import hashlib
import re

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
    formatted = parsed.dt.strftime("%Y-%m-%d")
    # dt.strftime can expose NaT as "NaT"; also reject malformed/out-of-bounds dates.
    return formatted.where(formatted.str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False))


def _province_column(frame: pd.DataFrame) -> pd.Series:
    text = _clean_text_column(frame, "recipient_province")
    upper = text.str.upper()
    mapped = text.str.casefold().map(PROVINCE_CODES)
    return upper.where(upper.isin(VALID_PROVINCE_CODES), mapped)


def _department_column(frame: pd.DataFrame) -> pd.Series:
    title = _clean_text_column(frame, "owner_org_title")
    english_title = title.str.split(" | ", n=1, regex=False).str[0]
    return english_title.fillna(_clean_text_column(frame, "owner_org"))


def _amendment_number_column(frame: pd.DataFrame) -> pd.Series:
    """Parse amendment numbers; missing means the original agreement (0).

    Non-integer or negative values become missing so validation rejects them.
    """
    text = _clean_text_column(frame, "amendment_number").fillna("0")
    numbers = pd.to_numeric(text, errors="coerce")
    valid = numbers.notna() & (numbers >= 0) & (numbers == numbers.round())
    return numbers.where(valid).astype("Int64")


def _hashed_id(prefix: str, identity: pd.Series) -> pd.Series:
    return identity.map(
        lambda value: f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"
    )


def _identity_columns(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return stable (record_id, agreement_id) columns.

    Departments reuse reference numbers (for example ``GC-2017-Q4-00160``), so
    an agreement is identified by the owning organization plus its reference
    number. A record is one amendment of that agreement.
    """
    reference = _clean_text_column(frame, "ref_number")
    owner = _clean_text_column(frame, "owner_org").fillna("")
    amendment = _amendment_number_column(frame).astype("string").fillna("invalid")
    agreement_identity = "goc-grants:v2:" + owner + ":" + reference
    primary_identity = agreement_identity + ":" + amendment

    fallback_identity = _fallback_identity(frame)
    has_reference = reference.notna()
    record_identity = primary_identity.where(has_reference, fallback_identity)
    agreement_identity = agreement_identity.where(has_reference, fallback_identity)
    return (
        _hashed_id("grant", record_identity),
        _hashed_id("agreement", agreement_identity),
    )


def _fallback_identity(frame: pd.DataFrame) -> pd.Series:
    """Content identity for rows without a reference number."""
    return (
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


def clean_chunk(
    frame: pd.DataFrame,
    *,
    source_url: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    """Normalize and map a CSV chunk into canonical records."""
    normalized = normalize_columns(frame)
    record_id, agreement_id = _identity_columns(normalized)
    records = pd.DataFrame(
        {
            "record_id": record_id,
            "agreement_id": agreement_id,
            "reference_number": _clean_text_column(normalized, "ref_number"),
            "amendment_number": _amendment_number_column(normalized),
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
                "prog_name_en",
                "prog_name_fr",
                "prog_purpose_en",
                "prog_purpose_fr",
                "description_en",
                "description_fr",
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
                "prog_purpose_en",
                "prog_purpose_fr",
            ),
            "source_url": source_url,
            "retrieved_at": retrieved_at,
        },
        index=normalized.index,
    )
    ordered = records.loc[:, CANONICAL_FIELDS].astype(object)
    return ordered.where(pd.notna(ordered), None).to_dict(orient="records")
