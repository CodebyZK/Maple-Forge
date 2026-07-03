# Maple Forge

Maple Forge is the data pipeline repository for MapleScope.

It downloads, cleans, validates, and exports Canadian federal grants and contributions data into a stable JSON format for downstream projects.

## Status

Current milestone: `v0.1.0`

This repository currently contains the project scaffold only.

## Data source

Maple Forge uses the Government of Canada Grants and Contributions dataset.

Required attribution:

> Contains information licensed under the Open Government Licence - Canada.

## Planned commands

```bash
maple-forge-download
maple-forge-export-sample
pytest
```

## Scope

In scope:

- Download the official federal grants CSV
- Preserve source URL and UTC retrieval timestamp
- Normalize source column names
- Clean and validate records
- Export a deterministic 500-record JSON sample
- Run tests without live internet access

Out of scope:

- Web application
- Database
- Authentication or user accounts
- Email alerts
- AI summaries or purchasing predictions
- Provincial or municipal datasets
- Contracts, lobbying, or political-financing data

## Architecture

Maple Forge is intentionally split into small pipeline modules:

```text
src/maple_forge/
├── config.py
├── download.py
├── clean.py
├── validate.py
└── export.py
```

Each module has a narrow responsibility:

- `download.py` retrieves the source CSV and records source metadata.
- `clean.py` normalizes source columns and maps records into the canonical schema.
- `validate.py` checks required fields and reports rejected rows.
- `export.py` writes the deterministic sample JSON output.
- `config.py` stores shared paths and constants.

## Development setup

Create and activate a virtual environment:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project with development dependencies:

```powershell
pip install -e ".[dev]"
```

Run tests:

```powershell
pytest
```

## Data rules

Do not commit the complete raw or processed dataset.

The repository should only commit:

- small fixtures used by tests
- `.gitkeep` files needed to preserve folder structure
- the required 500-record sample once the export pipeline is implemented

## License

Project code is licensed under the MIT License.

Government of Canada source data remains subject to the Open Government Licence - Canada.
