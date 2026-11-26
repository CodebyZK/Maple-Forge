import pandas as pd

from maple_forge.recipients import (
    MAX_NAMES_PER_BUSINESS_NUMBER,
    assign_recipient_ids,
    looks_like_person,
    normalize_name,
    valid_business_number,
)


def test_normalize_name_drops_legal_suffixes_accents_and_punctuation() -> None:
    assert normalize_name("Bombardier Inc.") == "bombardier"
    assert normalize_name("BOMBARDIER INCORPORATED") == "bombardier"
    assert normalize_name("The Société Ltée") == "societe"
    assert normalize_name("Smith & Sons Co. Ltd.") == "smith and sons"
    assert normalize_name("Acme Ltd. | Acme Ltée") == "acme"
    assert normalize_name("  ") is None


def test_valid_business_number_rejects_placeholders() -> None:
    assert valid_business_number("727927121RC0001") == "727927121"
    assert valid_business_number(" 801131574 ") == "801131574"
    for placeholder in ("0", "000000000", "999999999", "123456789", "-", None):
        assert valid_business_number(placeholder) is None


def test_looks_like_person() -> None:
    assert looks_like_person("Anyone, Some", "P")
    assert not looks_like_person("Anyone Corp", "P")
    assert looks_like_person("Jakobi, Jennifer", "S")
    assert looks_like_person("Jakobi, Jennifer", None)
    assert not looks_like_person("Toronto, City of", None)
    assert not looks_like_person("Jakobi, Jennifer", "F")
    assert not looks_like_person("University of Toronto", "S")


def _frame(rows: list[tuple[str, str | None, str | None, str | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["recipient_name", "recipient_type", "business_number", "province"]
    )


def test_name_variants_with_one_business_number_share_an_id() -> None:
    assigned = assign_recipient_ids(
        _frame(
            [
                ("Acme Inc.", "F", "111111112", "ON"),
                ("ACME INCORPORATED", "F", "111111112", "QC"),
                ("Acme Robotics", "F", "111111112", "ON"),
                ("Acme Inc.", "F", None, "ON"),
                ("Other Co", "F", "222222223", "ON"),
            ]
        )
    )
    ids = assigned["recipient_id"]
    assert not assigned["recipient_is_person"].any()
    assert ids[0] == ids[1] == ids[2]
    assert ids[3] != ids[0]
    assert ids[4] != ids[0]
    assert all(value.startswith("recipient_") for value in ids)


def test_shared_university_number_never_merges_people_or_orgs() -> None:
    rows = [(f"Smith{index}, Anna", "P", "333333334", "ON") for index in range(3)]
    rows += [
        (f"Lab {index}", "S", "444444445", "ON")
        for index in range(MAX_NAMES_PER_BUSINESS_NUMBER + 1)
    ]
    assigned = assign_recipient_ids(_frame(rows))
    ids = assigned["recipient_id"]
    assert ids.nunique() == len(rows)


def test_people_are_keyed_by_name_and_province() -> None:
    assigned = assign_recipient_ids(
        _frame(
            [
                ("Tong, Michelle", "P", None, "ON"),
                ("TONG, Michelle", "P", "108161779", "ON"),
                ("Tong, Michelle", "P", None, "BC"),
            ]
        )
    )
    ids = assigned["recipient_id"]
    assert assigned["recipient_is_person"].all()
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]


def test_placeholder_names_are_aggregates_not_people_or_orgs() -> None:
    assigned = assign_recipient_ids(
        _frame(
            [
                ("batch report\u2502rapport en lots", None, None, "ON"),
                ("Batch report |rapport en lots", "P", None, "QC"),
                ("BATCH REPORT VICTIMS OF CRIME (PAROLE COMPONENT)", None, None, None),
                ("Withheld | Retenu", "P", "111111112", "ON"),
                ("Batchewana First Nation", "A", None, "ON"),
            ]
        )
    )
    ids = assigned["recipient_id"]
    assert assigned["recipient_is_aggregate"].tolist() == [True, True, True, True, False]
    assert not assigned["recipient_is_person"][:4].any()
    assert ids[0] == ids[1] == ids[2]
    assert ids[3] != ids[0]


def test_missing_and_blank_names_do_not_break_assignment() -> None:
    assigned = assign_recipient_ids(
        _frame([(None, None, None, None), ("  ", "F", "555555556", "ON"), ("Acme", "F", None, None)])
    )
    assert not assigned["recipient_is_aggregate"].any()
    assert assigned["recipient_id"].notna().all()


def test_company_markers_override_person_type_and_name_shape() -> None:
    for name in (
        "2076729 Alberta Inc.",
        "TSOLUM FISHING CORPORATION",
        "Shamrock Colony Farming Co. Ltd., and 1648258 Alberta Ltd.",
        "Native Women's Association of Canada",
        "Lyle Wood (o/a Locustwood Farms, Tyler Wood)",
        "LAVAL POINCON & MATRICE LTéE",
    ):
        assert not looks_like_person(name, "P"), name
    assert not looks_like_person("Info-Tech Research Group, Inc.", "O")
    assert looks_like_person("Hu, Zhiying", "P")
    assert looks_like_person("Farmer, Jane", "P")
    assert looks_like_person("Inch, Robert", "S")


def test_punctuated_business_numbers_keep_their_root() -> None:
    assert valid_business_number("123-456-782") == "123456782"
    assert valid_business_number("123 456 782 RC0001") == "123456782"
    assert valid_business_number("12-345") is None
    assert valid_business_number("111-111-111") is None


def test_organization_words_override_person_type() -> None:
    assert not looks_like_person("Toronto, City of", "P")
    assert not looks_like_person("Kelowna School District", "P")
    assert looks_like_person("Tong, Michelle", "P")
