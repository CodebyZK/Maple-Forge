# Canonical data dictionary

Maple Forge normalizes source column labels to lowercase snake_case before
mapping them. English fields are preferred where the source publishes English
and French variants; the French value is used when English is missing.

| Field | JSON type | Required | Source and transformation |
|---|---|---:|---|
| `record_id` | string | yes | `grant_` plus the first 24 hexadecimal characters of SHA-256 over `goc-grants:v2:{owner_org}:{ref_number}:{amendment_number}`. A documented content fallback is used when `ref_number` is missing. |
| `agreement_id` | string | yes | `agreement_` plus the first 24 hexadecimal characters of SHA-256 over `goc-grants:v2:{owner_org}:{ref_number}`. Shared by every amendment of one agreement. Rows without `ref_number` use the content fallback, so each is its own agreement. |
| `reference_number` | string/null | no | `ref_number` with whitespace normalized. Not unique on its own: departments reuse reference numbers. |
| `amendment_number` | integer | yes | `amendment_number` as a non-negative integer. Missing means `0`, the original agreement. Non-integer or negative values reject the record. |
| `recipient_name` | string | yes | First non-empty value from `recipient_legal_name`, `recipient_operating_name`, or `research_organization_name`. |
| `recipient_type` | string/null | no | `recipient_type` code when it is one of `A` (Indigenous), `F` (for-profit), `G` (government), `I` (international), `N` (not-for-profit), `O` (other), `P` (individual), `S` (academic). |
| `business_number` | string/null | no | First 9 digits of `recipient_business_number`. Placeholders (`0`, repeated digits, `123456789`, `987654321`) become null. |
| `agreement_title` | string | yes | First non-empty value from the agreement title fields or `agreement_number`, falling back to the published program name, program purpose, or description for older records. |
| `agreement_value` | number | yes | `agreement_value`, parsed as a finite Canadian-dollar number. Currency symbols and thousands separators are removed. |
| `agreement_start_date` | string/null | no | `agreement_start_date`, parsed as an ISO 8601 `YYYY-MM-DD` date. |
| `agreement_end_date` | string/null | no | `agreement_end_date`, parsed as an ISO 8601 `YYYY-MM-DD` date. |
| `province` | string/null | no | `recipient_province`, normalized to a Canadian two-letter postal code when recognized. |
| `city` | string/null | no | `recipient_city`, with surrounding and repeated whitespace normalized. |
| `department` | string | yes | English portion of `owner_org_title`; falls back to `owner_org`. |
| `program_name` | string/null | no | First non-empty value from `prog_name_en` or `prog_name_fr`. |
| `description` | string/null | no | First non-empty value from `description_en` or `description_fr`, falling back to the published program purpose. |
| `source_url` | string | yes | Exact CSV URL stored in download metadata. |
| `retrieved_at` | string | yes | Download time from metadata as an ISO 8601 UTC datetime ending in `Z`. |
| `is_latest_amendment` | boolean | derived | `true` for the highest `amendment_number` of each `agreement_id`. Derived after the full pass. |
| `amendment_count` | integer | derived | Number of accepted amendment records for the record's `agreement_id`. |
| `recipient_id` | string | derived | Stable recipient identity; see below. |
| `recipient_is_person` | boolean | derived | Recipient type `P`, or a "Last, First" name under type `S`, `O` or none without organization words. |
| `recipient_is_aggregate` | boolean | derived | Placeholder rows that are not one recipient: names starting "Batch report" / "Rapport en lots", and "Withheld" / "Retenu". |

## Recipients

`recipient_id` is `recipient_` plus 24 hexadecimal characters of SHA-256 over
one of these keys:

- `aggregate:batch-report` or `aggregate:withheld` for placeholder rows;
- `org:bn:{business_number}` for organizations whose business number is
  shared by at most 10 distinct normalized names across the dataset;
- `person:{normalized name}|{province}` for individuals, who never use a
  business number (researchers and students are published under their
  institution's number, so one number can cover hundreds of people);
- `org:name:{normalized name}` otherwise.

Normalized names are case-folded, accent-free, use "and" for "&", keep only
the English part before `|`, and drop legal suffixes such as Inc., Ltd.,
Corp. and Ltée. The rules live in `src/maple_forge/recipients.py`.

## Amendments and totals

The source publishes one row per amendment, and each amendment row restates the
agreement's full amended value rather than the change. Summing every row
therefore counts amended agreements more than once. Consumers must sum
`agreement_value` only where `is_latest_amendment` is `true`. The other rows are
kept as amendment history.

In the 2026-07-04 source extract this matters: 1,303,900 rows describe
1,174,899 agreements. Summing every row gives $971.7B; summing latest
amendments gives $842.2B.

## Missing values

Optional missing values are serialized as JSON `null`. Missing or malformed
required values reject the record; they are not silently filled. Missing or
invalid dates and descriptions become `null` because those fields are optional.
Invalid monetary values reject the record because `agreement_value` is required.

## Duplicate handling

Rows with the same stable identity (`owner_org`, `ref_number`, and
`amendment_number`) are treated as duplicates. The first valid occurrence is
retained. Amendment zero and later amendments remain separate canonical
records.

Before schema 2.0.0 the identity omitted `owner_org`. Departments reuse
reference numbers, so 39,452 distinct grants from different departments were
wrongly discarded as duplicates.

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
timestamp column, `agreement_value` uses a double column,
`amendment_number` and `amendment_count` use `int32`, and
`is_latest_amendment` uses a boolean column. Other canonical fields use string
columns.

`data/processed/grants.manifest.json` identifies schema version `2.1.0`, copies
the available source URL, retrieval time, byte count, and source checksum from
download metadata, and reports accepted, agreement (latest amendment),
duplicate, rejected, and sample row counts. It also records the path, row count, and SHA-256 checksum for each
generated artifact.
