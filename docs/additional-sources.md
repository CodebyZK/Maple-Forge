# Additional data sources

Research into government funding data beyond the federal Grants and
Contributions dataset, checked on 2026-11-26 through each portal's CKAN API
(metadata, field lists and row counts; no bulk downloads). Overlap figures were
measured against the Forge 2.1.0 build of the 2026-07-04 grants extract.

## Recommendation

Add sources in this order. Each one joins to existing recipient profiles
rather than becoming a separate site.

| # | Source | What it adds | Join to recipients | Effort |
|---|---|---|---|---|
| 1 | **CRA charity returns (T3010)** | Revenue, government funding by level, spending, programs, directors | Business number (exact) | Small |
| 2 | **Federal contracts over $10,000** | Contracts held by the same organizations ("money trail") | Normalized vendor name + postal code | Medium |
| 3 | **Federal corporations (Corporations Canada)** | Official name, status (active/dissolved), address | Business number (exact) | Small |
| 4 | **Public Accounts transfer payments** | Amounts actually paid each year, not just agreed | Recipient name + city + province | Medium |
| 5 | **Ontario Public Accounts payments** | Provincial payments to the same recipients | Recipient name | Medium |
| 6 | **Lobbying registrations and communications** | Which recipients lobby which institutions | Organization name | Medium |
| 7 | **Research council awards (NSERC, CIHR)** | Research detail for academic recipients | Institution name | Medium, individuals |

## Measured overlap

### Charities (exact business-number join)

- 79,766 registered charities with a business number (2024 list).
- **22,871** grant recipients with a business number are registered
  charities: 15.9% of organizations with a business number.
- They hold **$81.5B** of federal agreement value (10.3% of
  organization funding).

For these recipients a profile can show total revenue, revenue from federal
(line 4540), provincial (4550) and municipal (4560) governments, total
expenditures, and charitable programs, all from the charity's own filing.

### Federal contracts (name matching, sample)

Of the 40 largest for-profit grant recipients, at least **15** also hold
federal contracts, worth at least **$13.1B**. Examples:

| Recipient | Grants and contributions | Contracts |
|---|---|---|
| CAE Inc. | $1.0B | $6.6B |
| Telesat LEO | $685M | $2.5B |
| General Dynamics Ordnance and Tactical Systems | $642M | $2.0B |
| TELUS Communications | $272M | $1.7B |

This is a lower bound: exact normalized names miss variants such as
"IBM Canada Limited - IBM Canada Ltée", and common names hit the 500-result
search cap. Production matching should combine normalized names with
`vendor_postal_code`.

## Source details

| Source | Publisher | Rows / size | Updates | Licence | Key fields |
|---|---|---|---|---|---|
| [List of charities 2024](https://open.canada.ca/data/en/dataset/80c00cdb-1358-415c-bb8b-0de7f12675b8) | Canada Revenue Agency | 83.8k charities; identification 12.6 MB, financial data 20.1 MB (85 fields) | Yearly | OGL–Canada | `BN` (15 characters; first 9 are the business number) |
| [Proactive Publication – Contracts](https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b) | Treasury Board | 1.34M rows, 625 MB CSV, 43 fields | Quarterly | OGL–Canada | `vendor_name`, `vendor_postal_code`, `contract_value`, `owner_org`, `reference_number` |
| [Federal Corporations](https://open.canada.ca/data/en/dataset/0032ce54-c5dd-4b66-99a0-320a7b5e99f2) | ISED | Four CSVs (active/inactive, CBCA/other) | Daily | OGL–Canada | `Business number (BN)`, `Corporation number`, names, status, address |
| [Detailed Transfer Payments (Public Accounts)](https://open.canada.ca/data/en/dataset/69bdc3eb-e919-4854-bc52-a435a3e19092) | PSPC | One CSV per year | Yearly | OGL–Canada | Recipient name and location, department, current-year expenditure |
| [CanadaBuys contract history](https://open.canada.ca/data/en/dataset/4fe645a1-ffcd-40c1-9385-2c771be956a4) | PSPC | Yearly CSVs since 2009 | Monthly | OGL–Canada | Supplier, contract number, amounts, dates |
| [Lobbying Registrations](https://open.canada.ca/data/en/dataset/70ef2117-1095-4d77-80eb-b87f2bada2a4) and [Monthly Communication Reports](https://open.canada.ca/data/en/dataset/a34eb330-7136-4f5e-9f5f-3ba41df58b06) | Commissioner of Lobbying | Zipped CSVs | Weekly | Open Data Licence Agreement (check terms) | Client organization, subject matters, institutions, dates |
| [NSERC Awards Data](https://open.canada.ca/data/en/dataset/c1b0f627-8c29-427c-ab73-33968ad9176e) | NSERC | Yearly CSVs since 1991 | Yearly | OGL–Canada | Researcher, institution, program, amount, research area |
| [CIHR Grants and Awards](https://open.canada.ca/data/en/dataset/49edb1d7-5cb4-4fa7-897c-515d1aad5da3) | CIHR | Yearly XLSX (~11 MB) | Quarterly | OGL–Canada | Researcher, institution, program, amount |
| [Infrastructure Canada Projects](https://open.canada.ca/data/en/dataset/beee0771-dab9-4be8-9b80-f8e8b3fdfd9d) | Housing, Infrastructure and Communities | CSV, JSON | Weekly | OGL–Canada | Project, location, federal contribution |
| [Ontario Public Accounts: Detailed Schedule of Payments](https://data.ontario.ca/dataset/public-accounts-detailed-schedule-of-payments) | Ontario Treasury Board Secretariat | ~16k rows per year, 2014–15 to 2025–26 | Yearly | Ontario terms of use | Ministry, category (including transfer payments), recipient, amount |
| [BC CRF supplier payments](https://catalogue.data.gov.bc.ca/dataset/crf-detailed-schedules-of-payments-other-supplier-payments) | BC Financial Reporting | Small yearly CSVs | Yearly | OGL–BC | Supplier, amount (procurement, not grants) |
| [Toronto Community Grants Allocations](https://open.toronto.ca/dataset/community-grants-allocations/) | City of Toronto | CSV/JSON | Varies | OGL–Toronto | Organization, program, amount |

Not yet usable as structured open data: Alberta's grant payments disclosure
(the open "General Revenue Fund" files cover supplies, services and
procurement cards, not grants) and Quebec's provincial grants (only city-level
datasets were found, such as Montréal).

## Cautions

- **Individuals.** NSERC and CIHR publish researcher names, and the charity
  directors file lists people. Forge should keep the same rules as today:
  never use a person's institution's business number as their identity, and
  never show directors' names next to AI summaries.
- **Licences.** Most sources use the Open Government Licence – Canada. The
  lobbying data uses a separate Open Data Licence Agreement, and Ontario and
  Toronto have their own terms; each needs attribution in the site footer.
- **Different measures.** Grants are agreement values, contracts are contract
  values, and Public Accounts are cash paid in a year. Atlas must label them
  separately and never add them together.
- **Name matching.** Only charities and federal corporations join on business
  numbers. Every name-based join needs a confidence level and a way to report
  a wrong match.

## How Forge would ingest a new source

Each source becomes its own Forge stage with the same guarantees as the grants
pipeline (streaming download, validation, rejection report, manifest with
checksums, atomic publication):

```text
forge/src/maple_forge/sources/
├── grants.py        current pipeline
├── charities.py     T3010 identification + financial data, keyed by BN root
├── contracts.py     contracts, keyed by normalized vendor name + postal code
└── links.py         recipient_id <-> source record links with match method
```

- Outputs: `charities.parquet`, `contracts.parquet`, and
  `recipient_links.parquet` (`recipient_id`, `source`, `source_key`,
  `match_method` such as `business_number` or `name_postal`, `confidence`).
- Data API: recipient profiles gain `charity` and `contracts` sections from
  the link table; nothing changes for recipients without links.
- Atlas: new profile cards ("Charity financials", "Federal contracts") with
  their own source links and licences.
- Refresh: charities yearly, contracts quarterly, each publishing through the
  existing release mechanism.
