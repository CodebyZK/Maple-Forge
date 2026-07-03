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
SCHEMA_VERSION = "1.0.0"

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

CANONICAL_FIELDS = (
    "record_id",
    "recipient_name",
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

REQUIRED_FIELDS = (
    "record_id",
    "recipient_name",
    "agreement_title",
    "agreement_value",
    "department",
    "description",
    "source_url",
    "retrieved_at",
)
