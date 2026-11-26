"""Stable recipient identities for grouping grants by organization or person.

The source has no recipient identifier. Business numbers (BN) identify most
companies and non-profits, but they are unreliable on their own:

* placeholders such as ``000000000`` and ``123456789`` are common;
* researchers and students are published under their university's BN, so a
  single BN can cover hundreds of different people.

An organization therefore uses its BN only when that BN is valid and shared
by few normalized names. Everything else falls back to a normalized name.
People never use a BN, and their key includes the province to reduce merges
between different people who share a name.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

import pandas as pd

RECIPIENT_TYPES = {
    "A": "Indigenous recipient",
    "F": "For-profit organization",
    "G": "Government",
    "I": "International organization",
    "N": "Not-for-profit organization or charity",
    "O": "Other",
    "P": "Individual",
    "S": "Academic institution",
}

# A BN shared by more distinct normalized names than this is not treated as
# one organization (it is usually a university or a placeholder).
MAX_NAMES_PER_BUSINESS_NUMBER = 10

_LEGAL_SUFFIXES = (
    "incorporated",
    "incorporee",
    "inc",
    "limited",
    "limitee",
    "ltd",
    "ltee",
    "corporation",
    "corp",
    "company",
    "co",
    "llc",
    "llp",
    "lp",
    "plc",
    "ulc",
    "societe",
    "the",
)
_SUFFIX_PATTERN = re.compile(
    r"(?:\s+(?:" + "|".join(_LEGAL_SUFFIXES) + r"))+$"
)
_LEADING_THE = re.compile(r"^the\s+")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_PERSON_NAME = re.compile(r"^[^\W\d_][^,\d]*,\s*[^\W\d_][^,\d]*$")
_ORGANIZATION_WORDS = frozenset(
    {
        "association",
        "board",
        "centre",
        "center",
        "city",
        "college",
        "council",
        "county",
        "district",
        "foundation",
        "government",
        "institute",
        "municipality",
        "nation",
        "region",
        "school",
        "society",
        "town",
        "township",
        "university",
        "village",
    }
)
_PLACEHOLDER_NUMBERS = frozenset({"123456789", "987654321"})
# Legal forms, business words, "o/a" (operating as) and numbered companies.
_COMPANY_MARKERS = re.compile(
    r"\b(?:inc|ltd|limited|lt[eé]e|corp|corporation|incorporated|llc|llp|ulc|plc"
    r"|company|holdings|enterprises|farms?|farming|ferme|colony|ranch|group|groupe"
    r"|association|society|cooperative|co-op|partnership)\b"
    r"|\bo/a\b|\d{4,}",
    re.IGNORECASE,
)


def normalize_name(name: object) -> str | None:
    """Return a comparison key for a recipient name, or None when empty."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    text = unicodedata.normalize("NFKD", str(name).split("|", 1)[0])
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold().replace("&", " and ")
    text = _NON_ALPHANUMERIC.sub(" ", text).strip()
    text = _LEADING_THE.sub("", text)
    text = _SUFFIX_PATTERN.sub("", text).strip()
    return text or None


def valid_business_number(value: object) -> str | None:
    """Return the 9-digit BN root, or None for missing and placeholder values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    # The root is the leading run of digits, which some rows punctuate
    # ("123-456-789", "123 456 789 RC0001"); the program suffix follows it.
    leading = re.match(r"^[\d\s.\-]+", str(value).strip())
    digits = re.sub(r"\D", "", leading.group()) if leading else ""
    if len(digits) < 9:
        return None
    root = digits[:9]
    if len(set(root)) == 1 or root in _PLACEHOLDER_NUMBERS:
        return None
    return root


def has_company_marker(name: object) -> bool:
    """Whether a name is clearly a business or organization."""
    return name is not None and bool(_COMPANY_MARKERS.search(str(name)))


def looks_like_person(name: object, recipient_type: object) -> bool:
    """Whether a recipient should be treated as an individual.

    Departments sometimes tag companies as type P ("2076729 Alberta Inc.",
    "Tsolum Fishing Corporation"), and "Name, Inc." looks like "Last, First",
    so company markers override both the type and the name shape.
    """
    if name is None or has_company_marker(name):
        return False
    text = str(name).strip()
    tokens = set(_NON_ALPHANUMERIC.sub(" ", text.casefold()).split())
    # Organization words ("Toronto, City of") also override a type P tag.
    if tokens & _ORGANIZATION_WORDS:
        return False
    if recipient_type == "P":
        return True
    if recipient_type not in (None, "S", "O"):
        return False
    if not _PERSON_NAME.match(text):
        return False
    return bool(tokens) and len(tokens) <= 5


def _hash(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def aggregate_kind(normalized_name: object) -> str | None:
    """Placeholder kind for rows that are not one real recipient, else None.

    Departments publish small grants in aggregate as "Batch report | Rapport en
    lots", and redacted recipients as "Withheld | Retenu".
    """
    # pandas turns missing names into NaN (a float) when mapping a column.
    if not isinstance(normalized_name, str) or not normalized_name:
        return None
    if normalized_name.startswith(("batch report", "rapport en lots")):
        return "batch-report"
    if normalized_name in {"withheld", "withheld retenu", "retenu"}:
        return "withheld"
    return None


def assign_recipient_ids(frame: pd.DataFrame) -> pd.DataFrame:
    """Assign recipient_id, recipient_is_person and recipient_is_aggregate.

    ``frame`` needs ``recipient_name``, ``recipient_type``, ``business_number``
    and ``province`` columns. The assignment depends on every row, because a
    BN is trusted only when few distinct names share it.
    """
    names = frame["recipient_name"].map(normalize_name)
    aggregates = names.map(aggregate_kind)
    is_aggregate = aggregates.notna()
    is_person = pd.Series(
        [
            looks_like_person(name, kind)
            for name, kind in zip(
                frame["recipient_name"], frame["recipient_type"], strict=True
            )
        ],
        index=frame.index,
    ) & ~is_aggregate
    business_numbers = frame["business_number"].where(~is_person & ~is_aggregate)

    names_per_number = (
        pd.DataFrame({"bn": business_numbers, "name": names})
        .dropna()
        .groupby("bn")["name"]
        .nunique()
    )
    trusted_numbers = set(
        names_per_number[names_per_number <= MAX_NAMES_PER_BUSINESS_NUMBER].index
    )
    use_number = business_numbers.isin(trusted_numbers)

    province = frame["province"].fillna("").astype(str)
    fallback_name = names.fillna("").astype(str)
    keys = pd.Series("org:name:" + fallback_name, index=frame.index)
    keys = keys.where(~is_person, "person:" + fallback_name + "|" + province)
    keys = keys.where(~use_number, "org:bn:" + business_numbers.astype(str))
    keys = keys.where(~is_aggregate, "aggregate:" + aggregates.fillna(""))
    return pd.DataFrame(
        {
            "recipient_id": keys.map(lambda key: _hash("recipient", key)),
            "recipient_is_person": is_person.astype(bool),
            "recipient_is_aggregate": is_aggregate.astype(bool),
        },
        index=frame.index,
    )
