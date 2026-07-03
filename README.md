# Maple Forge

Maple Forge is the data pipeline repository for MapleScope. It downloads,
cleans, validates, and exports Canadian federal grants and contributions data
into a stable JSON format for downstream projects.

Current milestone: `v0.1.0`

## Data source

The pipeline uses the Government of Canada
[Proactive Disclosure - Grants and Contributions dataset](https://open.canada.ca/data/en/dataset/432527ab-7aac-45b5-81d6-7597107a7013).
The direct CSV resource is configurable because resource URLs may change.

> Contains information licensed under the Open Government Licence - Canada.

The complete CSV is currently several gigabytes. Maple Forge streams downloads
and reads the CSV in chunks rather than loading the full file into memory.

## Setup

Python 3.12 or newer is required.

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Bash or zsh:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the pipeline

Download the official CSV and write retrieval metadata:

PowerShell:

```powershell
maple-forge-download
maple-forge-export-sample
```

Bash or zsh:

```bash
maple-forge-download
maple-forge-export-sample
```

The export command cleans and validates the downloaded data, reports rejected
records, and writes the deterministic 500-record sample.

The commands create these ignored working files and committed output:

- `data/raw/grants.csv`: complete source CSV, not committed
- `data/raw/grants.metadata.json`: URL, UTC retrieval time, byte count, and SHA-256
- `data/processed/grants.rejected.jsonl`: one validation report per rejected row
- `data/samples/grants.sample.json`: deterministic canonical sample

Override the resource URL when necessary:

PowerShell:

```powershell
$env:MAPLE_FORGE_GRANTS_CSV_URL = "https://example.gc.ca/grants.csv"
maple-forge-download
```

Bash or zsh:

```bash
export MAPLE_FORGE_GRANTS_CSV_URL="https://example.gc.ca/grants.csv"
maple-forge-download
```

Every command also supports `--help` and explicit path arguments.

## Tests

PowerShell, bash, or zsh:

```console
pytest
```

Tests use synthetic fixtures and mocked HTTP responses. They do not require
network access.

## Architecture

```text
src/maple_forge/
├── config.py      shared paths, source URL, and schema constants
├── download.py    streaming HTTP download and retrieval metadata
├── clean.py       source normalization and canonical field mapping
├── validate.py    accepted/rejected record partitioning
└── export.py      chunked processing and deterministic JSON export
```

The deterministic sample contains the records with the 500 lexicographically
smallest stable IDs and is sorted by `record_id`. IDs are derived from the
source `ref_number` and `amendment_number`, so they do not depend on CSV row
order.

See [data-sources.md](docs/data-sources.md) for source lineage and
[data-dictionary.md](docs/data-dictionary.md) for field mappings and
validation rules.

## Limitations

- The pipeline covers the federal grants and contributions CSV only.
- English source text is preferred, with French used as a fallback.
- Province and territory values are normalized only when they match a known
  Canadian name or postal abbreviation.
- Repeated source identities are treated as duplicates. Conflicting rows with
  the same reference and amendment identifier retain the first occurrence.
- Exact cross-chunk deduplication keeps accepted record IDs in memory. If the
  source grows substantially, this index should move to bounded on-disk storage.
- The committed sample is for development and demonstration, not statistical
  analysis.

## Data policy

Do not commit the complete raw or processed dataset. Only small test fixtures,
directory placeholders, and the required 500-record sample belong in Git.

## License

Project code is licensed under the MIT License. Government of Canada source
data remains subject to the Open Government Licence - Canada.
