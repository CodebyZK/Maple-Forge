# Data sources

## Federal grants and contributions

- Publisher: Treasury Board of Canada Secretariat
- Dataset: [Proactive Disclosure - Grants and Contributions](https://open.canada.ca/data/en/dataset/432527ab-7aac-45b5-81d6-7597107a7013)
- Format: UTF-8 CSV
- Update frequency: quarterly
- Licence: Open Government Licence - Canada

Required attribution:

> Contains information licensed under the Open Government Licence - Canada.

The default resource configured in `maple_forge.config` is the official CSV
linked from the dataset page. It can be overridden with the
`MAPLE_FORGE_GRANTS_CSV_URL` environment variable or `maple-forge-download
--url`.

## Lineage

`maple-forge-download` records the exact resource URL, UTC retrieval timestamp,
downloaded byte count, and SHA-256 digest in `data/raw/grants.metadata.json`.
The URL and timestamp are copied into every canonical record.

The exporter reads the CSV in chunks. It normalizes source labels, maps the
documented fields, validates each canonical record, writes rejected rows to a
JSON Lines report, and removes repeated source identities. A single build writes
every accepted record to `data/processed/grants.parquet`, selects the
deterministic JSON sample, and records lineage, counts, and artifact checksums
in `data/processed/grants.manifest.json`.

Raw and processed files are intentionally ignored by Git because the complete
source is large and is republished regularly.
