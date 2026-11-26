from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from maple_forge.charities import build_charities, clean_charities, recipient_links
from maple_forge.recipients import _hash

IDENTIFICATION = """BN/NE,Category/Catégorie,Sub Category/Sous-catégorie,Designation/Désignation,Legal Name/Dénomination,Account Name/Nom du compte,Address Line 1,Address Line 2,City/Ville,Province,Postal Code,Country
108161779RR0001,0010,0014,C,UNIVERSITY OF EXAMPLE,UNIVERSITY OF EXAMPLE,1 Main,,VANCOUVER,BC,V6T1Z4,CA
222222223RR0001,0160,,C,SMALL COMMUNITY CENTRE,,2 Main,,OTTAWA,ON,K1A0A1,CA
333333334RR0001,0210,,B,FAMILY FOUNDATION,,3 Main,,TORONTO,ON,M5V1A1,CA
000000000RR0001,0010,,C,PLACEHOLDER,,,,,,,
"""

FINANCIAL_HEADER = "BN,FPE,Form ID,Section Used,4540,4550,4560,4570,4700,5000,5010,5020,5100,4200,4350"
FINANCIAL = FINANCIAL_HEADER + """
108161779RR0001,2023-03-31,26,6,300,1000,5,,3000,2500,150,10,2900,8000,5000
108161779RR0001,2024-03-31,27,6,380,1200,,,3700,3300,200,,3500,8300,5600
222222223RR0001,2024-12-31,27,D,,,,40,90,70,10,,85,,
333333334RR0001,2024-06-30,27,6,,,,,500,0,20,,20,9000,
"""


def _grants(tmp_path: Path) -> Path:
    rows = [
        # Organization identified by its own BN: links.
        {"recipient_id": _hash("recipient", "org:bn:108161779"), "business_number": "108161779",
         "recipient_name": "University of Example", "recipient_is_person": False,
         "recipient_is_aggregate": False},
        # A researcher filed under the university's BN: must not link.
        {"recipient_id": "recipient_person", "business_number": "108161779",
         "recipient_name": "Doe, Jane", "recipient_is_person": True, "recipient_is_aggregate": False},
        # An organization grouped by name whose name differs from the charity's:
        # must not link.
        {"recipient_id": "recipient_by_name", "business_number": "222222223",
         "recipient_name": "Community Centre Kitchen Project",
         "recipient_is_person": False, "recipient_is_aggregate": False},
        # A foundation grouped by name whose name equals the charity's: links.
        {"recipient_id": "recipient_foundation", "business_number": "333333334",
         "recipient_name": "Family Foundation", "recipient_is_person": False,
         "recipient_is_aggregate": False},
    ]
    path = tmp_path / "grants.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def test_links_by_business_number_identity_or_matching_name(tmp_path: Path) -> None:
    links = recipient_links(_grants(tmp_path))

    assert links.by_number == {"108161779": _hash("recipient", "org:bn:108161779")}
    assert links.by_name == {
        ("222222223", "community centre kitchen project"): "recipient_by_name",
        ("333333334", "family foundation"): "recipient_foundation",
    }


def test_clean_charities_maps_codes_amounts_and_latest_return(tmp_path: Path) -> None:
    from io import StringIO

    charities = clean_charities(
        pd.read_csv(StringIO(IDENTIFICATION), dtype=str),
        pd.read_csv(StringIO(FINANCIAL), dtype=str),
        recipient_links(_grants(tmp_path)),
    ).set_index("business_number")

    assert len(charities) == 3  # the placeholder BN is dropped
    university = charities.loc["108161779"]
    assert university["designation"] == "Charitable organization"
    assert university["category"] == "Teaching institutions"
    assert str(university["fiscal_period_end"]) == "2024-03-31"
    assert university["revenue_federal"] == 380
    assert pd.isna(university["revenue_municipal"])  # blank means not reported
    assert university["revenue_government_total"] == 1580
    assert university["recipient_id"] == _hash("recipient", "org:bn:108161779")

    small = charities.loc["222222223"]
    assert small["section_used"] == "D"
    assert small["revenue_government_total"] == 40  # Section D combined amount
    assert pd.isna(small["recipient_id"])

    foundation = charities.loc["333333334"]
    assert foundation["recipient_id"] == "recipient_foundation"  # name match
    assert foundation["designation"] == "Private foundation"
    assert foundation["charitable_programs"] == 0
    assert pd.isna(foundation["revenue_government_total"])


def test_build_charities_writes_parquet_and_manifest(tmp_path: Path) -> None:
    identification = tmp_path / "identification.csv"
    financial = tmp_path / "financial.csv"
    identification.write_text(IDENTIFICATION, encoding="utf-8")
    financial.write_text(FINANCIAL, encoding="utf-8")

    summary = build_charities(
        identification, financial, _grants(tmp_path),
        tmp_path / "out" / "charities.parquet", tmp_path / "out" / "charities.manifest.json",
    )

    table = pq.read_table(summary.output_path)
    assert summary.charity_count == 3
    assert summary.linked_count == 2
    assert table.schema.field("fiscal_period_end").type == pa.date32()
    assert not list((tmp_path / "out").glob("*.part"))
    manifest = summary.manifest_path.read_text(encoding="utf-8")
    assert '"linked_recipients": 2' in manifest
    assert "Open Government Licence" in manifest
