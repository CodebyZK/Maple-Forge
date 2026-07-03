# Canonical data dictionary

Maple Forge normalizes source column labels to lowercase snake_case before
mapping them. English fields are preferred where the source publishes English
and French variants; the French value is used when English is missing.

| Field | JSON type | Required | Source and transformation |
|---|---|---:|---|
| `record_id` | string | yes | `grant_` plus the first 24 hexadecimal characters of SHA-256 over the namespace, `ref_number`, and `amendment_number`. A documented content fallback is used when `ref_number` is missing. |
| `recipient_name` | string | yes | First non-empty value from `recipient_legal_name`, `recipient_operating_name`, or `research_organization_name`. |
| `agreement_title` | string | yes | First non-empty value from `agreement_title_en`, `agreement_title_fr`, or `agreement_number`. |
| `agreement_value` | number | yes | `agreement_value`, parsed as a finite Canadian-dollar number. Currency symbols and thousands separators are removed. |
| `agreement_start_date` | string/null | no | `agreement_start_date`, parsed as an ISO 8601 `YYYY-MM-DD` date. |
| `agreement_end_date` | string/null | no | `agreement_end_date`, parsed as an ISO 8601 `YYYY-MM-DD` date. |
| `province` | string/null | no | `recipient_province`, normalized to a Canadian two-letter postal code when recognized. |
| `city` | string/null | no | `recipient_city`, with surrounding and repeated whitespace normalized. |
| `department` | string | yes | English portion of `owner_org_title`; falls back to `owner_org`. |
| `program_name` | string/null | no | First non-empty value from `prog_name_en` or `prog_name_fr`. |
| `description` | string | yes | First non-empty value from `description_en` or `description_fr`. |
| `source_url` | string | yes | Exact CSV URL stored in download metadata. |
| `retrieved_at` | string | yes | Download time from metadata as an ISO 8601 UTC datetime ending in `Z`. |

## Missing values

Optional missing values are serialized as JSON `null`. Missing or malformed
required values reject the record; they are not silently filled. Invalid dates
become `null` because dates are optional. Invalid monetary values reject the
record because `agreement_value` is required.

## Duplicate handling

Rows with the same stable identity (`ref_number` and `amendment_number`) are
treated as duplicates. The first valid occurrence is retained. Amendment zero
and later amendments remain separate canonical records.

## Rejected rows

Rejected records are written to `data/processed/grants.rejected.jsonl`. Each
line contains:

```json
{
  "errors": ["recipient_name is required"],
  "record": {}
}
```

The `record` object contains the complete attempted canonical mapping.

## Published artifacts

`data/processed/grants.parquet` contains one row per accepted unique record.
Agreement dates use native Parquet `date32` columns, `retrieved_at` uses a UTC
timestamp column, and `agreement_value` uses a double column. Other canonical
fields use string columns.

`data/processed/grants.manifest.json` identifies schema version `1.0.0`, copies
the available source URL, retrieval time, byte count, and source checksum from
download metadata, and reports accepted, duplicate, rejected, and sample row
counts. It also records the path, row count, and SHA-256 checksum for each
generated artifact.
