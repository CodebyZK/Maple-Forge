"""Configuration constants for Maple Forge."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLES_DIR = DATA_DIR / "samples"

RAW_GRANTS_CSV = RAW_DIR / "grants.csv"
RAW_METADATA_JSON = RAW_DIR / "grants.metadata.json"
SAMPLE_JSON = SAMPLES_DIR / "grants.sample.json"
PROCESSED_GRANTS_PARQUET = PROCESSED_DIR / "grants.parquet"
REJECTED_JSONL = PROCESSED_DIR / "grants.rejected.jsonl"
MANIFEST_JSON = PROCESSED_DIR / "grants.manifest.json"

SAMPLE_SIZE = 500
CSV_CHUNK_SIZE = 10_000
SCHEMA_VERSION = "2.1.0"

GRANTS_CSV_URL_ENV_VAR = "MAPLE_FORGE_GRANTS_CSV_URL"

DATASET_PAGE_URL = (
    "https://open.canada.ca/data/en/dataset/"
    "432527ab-7aac-45b5-81d6-7597107a7013"
)
DEFAULT_GRANTS_CSV_URL = (
    "https://open.canada.ca/data/dataset/"
    "432527ab-7aac-45b5-81d6-7597107a7013/resource/"
    "1d15a62f-5656-49ad-8c88-f40ce689d831/download/grants.csv"
)

# Fields produced for every source row by ``clean_chunk``.
CANONICAL_FIELDS = (
    "record_id",
    "agreement_id",
    "reference_number",
    "amendment_number",
    "recipient_name",
    "recipient_type",
    "business_number",
    "agreement_title",
    "agreement_value",
    "agreement_start_date",
    "agreement_end_date",
    "province",
    "city",
    "department",
    "program_name",
    "description",
    "source_url",
    "retrieved_at",
)

# Fields derived after a complete pass, because they depend on other rows
# (every amendment of an agreement, every name sharing a business number).
# They are present in published Parquet and sample records.
DERIVED_FIELDS = (
    "is_latest_amendment",
    "amendment_count",
    "recipient_id",
    "recipient_is_person",
    "recipient_is_aggregate",
)

PUBLISHED_FIELDS = (*CANONICAL_FIELDS, *DERIVED_FIELDS)

REQUIRED_FIELDS = (
    "record_id",
    "agreement_id",
    "amendment_number",
    "recipient_name",
    "agreement_title",
    "agreement_value",
    "department",
    "source_url",
    "retrieved_at",
)
