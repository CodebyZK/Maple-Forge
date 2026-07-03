# Contributing to Maple Forge

Maple Forge is intentionally small and testable.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest