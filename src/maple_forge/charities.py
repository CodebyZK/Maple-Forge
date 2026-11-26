"""Registered charity data (CRA T3010 returns), linked to grant recipients.

Source: Canada Revenue Agency, "List of charities" open data, licensed under
the Open Government Licence - Canada. Each charity's business number (BN) is
the first nine characters of its registration number, the same root Forge
stores for grant recipients, so charities join to recipient profiles exactly.

Field meanings follow CRA's "List of charities data dictionary" (v2.0):

    4540  Revenue received from federal government
    4550  Revenue received from provincial/territorial governments
    4560  Revenue received from municipal/regional governments
    4570  Amount received from any level of Canadian government
    4700  Total revenue
    5000  Total charitable programs expenditures
    5010  Total management and administration expenditures
    5020  Total fundraising expenditures
    5100  Total expenditures
    4200  Total assets
    4350  Total liabilities

Amounts are empty for exempt charities; empty means "not reported", never 0.
Schedule 6 filers report government revenue by level (4540-4560); Section D
filers report one combined amount (4570).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from maple_forge import config
from maple_forge.download import download_grants
from maple_forge.io import write_json_atomic
from maple_forge.recipients import valid_business_number

LOGGER = logging.getLogger(__name__)

CHARITIES_DIR = config.DATA_DIR / "charities"
CHARITIES_YEAR = "2024"
DATASET_PAGE_URL = (
    "https://open.canada.ca/data/en/dataset/80c00cdb-1358-415c-bb8b-0de7f12675b8"
)
IDENTIFICATION_URL = (
    "https://open.canada.ca/data/dataset/80c00cdb-1358-415c-bb8b-0de7f12675b8/"
    "resource/694fdc72-eae4-4ee0-83eb-832ab7b230e3/download"
)
FINANCIAL_URL = (
    "https://open.canada.ca/data/dataset/80c00cdb-1358-415c-bb8b-0de7f12675b8/"
    "resource/e545170c-3689-4833-b2a8-e9e83100ab59/download"
)
SCHEMA_VERSION = "1.0.0"

DESIGNATIONS = {
    "A": "Public foundation",
    "B": "Private foundation",
    "C": "Charitable organization",
}

# CRA "Codes Lists" (2.1 Categories).
CATEGORIES = {
    "0001": "Organizations relieving poverty",
    "0002": "Foundations relieving poverty",
    "0010": "Teaching institutions",
    "0011": "Support of schools and education",
    "0012": "Education in the arts",
    "0013": "Educational organizations not elsewhere categorized",
    "0014": "Research",
    "0015": "Foundations advancing education",
    "0030": "Christianity",
    "0040": "Islam",
    "0050": "Judaism",
    "0060": "Other religions",
    "0070": "Support of religion",
    "0080": "Ecumenical and inter-faith organizations",
    "0090": "Foundations advancing religions",
    "0100": "Core health care",
    "0110": "Supportive health care",
    "0120": "Protective health care",
    "0130": "Health care products",
    "0140": "Complementary or alternative health care",
    "0150": "Relief of the aged",
    "0155": "Upholding human rights",
    "0160": "Community resource",
    "0170": "Environment",
    "0175": "Agriculture",
    "0180": "Animal welfare",
    "0190": "Arts",
    "0200": "Public amenities",
    "0210": "Foundations",
    "0215": "National arts service organization",
}

AMOUNT_FIELDS = {
    "4540": "revenue_federal",
    "4550": "revenue_provincial",
    "4560": "revenue_municipal",
    "4570": "revenue_government_reported",
    "4700": "total_revenue",
    "5000": "charitable_programs",
    "5010": "management_and_administration",
    "5020": "fundraising",
    "5100": "total_expenditures",
    "4200": "total_assets",
    "4350": "total_liabilities",
}

PARQUET_SCHEMA = pa.schema(
    [
        pa.field("business_number", pa.string()),
        pa.field("registration_number", pa.string()),
        pa.field("recipient_id", pa.string()),
        pa.field("legal_name", pa.string()),
        pa.field("account_name", pa.string()),
        pa.field("designation", pa.string()),
        pa.field("category", pa.string()),
        pa.field("city", pa.string()),
        pa.field("province", pa.string()),
        pa.field("fiscal_period_end", pa.date32()),
        pa.field("section_used", pa.string()),
        *[pa.field(name, pa.float64()) for name in AMOUNT_FIELDS.values()],
        pa.field("revenue_government_total", pa.float64()),
        pa.field("list_year", pa.string()),
    ]
)


@dataclass(frozen=True)
class CharitySummary:
    charity_count: int
    linked_count: int
    output_path: Path
    manifest_path: Path


def _column(frame: pd.DataFrame, english: str) -> pd.Series:
    """A column by its English header ("BN", or a bilingual "BN/NE")."""
    wanted = english.casefold()
    for name in frame.columns:
        if str(name).strip().lstrip("﻿").split("/", 1)[0].strip().casefold() == wanted:
            return frame[name]
    raise KeyError(f"column {english!r} not found in {list(frame.columns)[:12]}")


def _text(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
    return cleaned.mask(cleaned == "")


def _amount(series: pd.Series) -> pd.Series:
    """Parse amounts; empty stays missing (not reported), never zero."""
    return pd.to_numeric(_text(series).str.replace(r"[,$\s]", "", regex=True), errors="coerce")


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path, dtype=str, encoding="utf-8-sig", keep_default_na=False, na_values=[""]
    )


def recipient_links(grants_parquet: Path) -> dict[str, str]:
    """Business number -> recipient_id, for recipients identified by their BN.

    Forge uses a BN as an organization's identity only when few names share
    it, and never for individuals, so a charity links to a recipient only when
    that recipient's identity is the charity's own business number.
    """
    from maple_forge.recipients import _hash  # noqa: PLC0415 - shared rule

    table = pq.read_table(
        grants_parquet,
        columns=["recipient_id", "business_number", "recipient_is_person", "recipient_is_aggregate"],
    ).to_pandas()
    table = table[
        table["business_number"].notna()
        & ~table["recipient_is_person"].astype(bool)
        & ~table["recipient_is_aggregate"].astype(bool)
    ].drop_duplicates(["recipient_id", "business_number"])
    links: dict[str, str] = {}
    for recipient_id, business_number in zip(
        table["recipient_id"], table["business_number"], strict=True
    ):
        if recipient_id == _hash("recipient", f"org:bn:{business_number}"):
            links[str(business_number)] = str(recipient_id)
    return links


def clean_charities(
    identification: pd.DataFrame,
    financial: pd.DataFrame,
    links: dict[str, str],
    *,
    list_year: str = CHARITIES_YEAR,
) -> pd.DataFrame:
    ident = pd.DataFrame(
        {
            "registration_number": _text(_column(identification, "BN")),
            "legal_name": _text(_column(identification, "Legal Name")),
            "account_name": _text(_column(identification, "Account Name")),
            "designation": _text(_column(identification, "Designation")).map(DESIGNATIONS),
            "category": _text(_column(identification, "Category")).str.zfill(4).map(CATEGORIES),
            "city": _text(_column(identification, "City")),
            "province": _text(_column(identification, "Province")),
        }
    )
    money = pd.DataFrame(
        {
            "registration_number": _text(_column(financial, "BN")),
            "fiscal_period_end": pd.to_datetime(
                _text(_column(financial, "FPE")), errors="coerce"
            ).dt.date,
            "section_used": _text(_column(financial, "Section Used")),
            **{
                name: _amount(_column(financial, code))
                for code, name in AMOUNT_FIELDS.items()
            },
        }
    )
    # A charity can file more than one return in a list year; keep the latest.
    money = money.sort_values("fiscal_period_end", na_position="first").drop_duplicates(
        "registration_number", keep="last"
    )

    charities = ident.dropna(subset=["registration_number"]).drop_duplicates(
        "registration_number", keep="last"
    ).merge(money, on="registration_number", how="left")
    charities["business_number"] = charities["registration_number"].map(valid_business_number)
    charities = charities.dropna(subset=["business_number"])

    by_level = charities[["revenue_federal", "revenue_provincial", "revenue_municipal"]]
    charities["revenue_government_total"] = by_level.sum(axis=1, min_count=1).where(
        by_level.notna().any(axis=1), charities["revenue_government_reported"]
    )
    charities["recipient_id"] = charities["business_number"].map(links)
    charities["list_year"] = list_year
    return charities.loc[:, PARQUET_SCHEMA.names]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_charities(
    identification_csv: Path,
    financial_csv: Path,
    grants_parquet: Path,
    output_path: Path,
    manifest_path: Path,
    *,
    list_year: str = CHARITIES_YEAR,
    source_metadata: dict[str, Any] | None = None,
) -> CharitySummary:
    charities = clean_charities(
        _read_csv(identification_csv),
        _read_csv(financial_csv),
        recipient_links(grants_parquet),
        list_year=list_year,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged = output_path.with_suffix(f"{output_path.suffix}.part")
    table = pa.Table.from_pandas(charities, schema=PARQUET_SCHEMA, preserve_index=False)
    pq.write_table(table, staged)
    linked = int(charities["recipient_id"].notna().sum())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "list_year": list_year,
        "dataset_page": DATASET_PAGE_URL,
        "licence": "Open Government Licence - Canada",
        "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": source_metadata or {},
        "grants_parquet_sha256": _sha256(grants_parquet),
        "counts": {"charities": len(charities), "linked_recipients": linked},
        "artifacts": {
            "parquet": {"path": output_path.name, "row_count": len(charities), "sha256": _sha256(staged)}
        },
    }
    staged.replace(output_path)
    write_json_atomic(manifest_path, manifest, sort_keys=True)
    LOGGER.info("Built %s charities, %s linked to grant recipients", f"{len(charities):,}", f"{linked:,}")
    return CharitySummary(len(charities), linked, output_path, manifest_path)


def download_charities(directory: Path = CHARITIES_DIR) -> dict[str, Any]:
    """Download the identification and financial files with their metadata."""
    return {
        "identification": download_grants(
            IDENTIFICATION_URL, directory / "identification.csv", directory / "identification.metadata.json"
        ),
        "financial": download_grants(
            FINANCIAL_URL, directory / "financial.csv", directory / "financial.metadata.json"
        ),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Download and link CRA charity data to grant recipients.")
    parser.add_argument("--download", action="store_true", help="download the CRA files first")
    parser.add_argument("--directory", type=Path, default=CHARITIES_DIR)
    parser.add_argument("--grants", type=Path, default=config.PROCESSED_GRANTS_PARQUET)
    parser.add_argument("--output", type=Path, default=config.PROCESSED_DIR / "charities.parquet")
    parser.add_argument("--manifest", type=Path, default=config.PROCESSED_DIR / "charities.manifest.json")
    parser.add_argument("--year", default=CHARITIES_YEAR)
    args = parser.parse_args()

    if args.download:
        metadata = download_charities(args.directory)
    else:
        metadata = {
            name: json.loads((args.directory / f"{name}.metadata.json").read_text(encoding="utf-8"))
            for name in ("identification", "financial")
            if (args.directory / f"{name}.metadata.json").is_file()
        }
    build_charities(
        args.directory / "identification.csv",
        args.directory / "financial.csv",
        args.grants,
        args.output,
        args.manifest,
        list_year=args.year,
        source_metadata=metadata,
    )
