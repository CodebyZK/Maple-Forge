# Contributing to Maple Forge

Maple Forge is intentionally small, testable, and deterministic.

## Local setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on macOS or Linux:

```bash
source .venv/bin/activate
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the project with development dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

## Development rules

- Do not commit the full raw dataset.
- Do not commit the full processed dataset.
- Keep download, clean, validate, and export logic separated.
- Tests must not require internet access.
- Document assumptions when mapping source columns.
- Keep the pipeline deterministic.
- Report invalid records instead of silently discarding them.

## Commit scope

Keep commits small and focused.

Recommended sequence:

1. Project scaffold
2. Download pipeline
3. Cleaning and normalization
4. Validation
5. Sample export
6. Documentation updates
7. CI updates

## Data policy

Only commit data files that are explicitly allowed by the project brief:

- `.gitkeep` files for folder structure
- small synthetic fixtures for tests
- the required 500-record sample once implemented

Do not commit complete raw or processed Government of Canada datasets.
