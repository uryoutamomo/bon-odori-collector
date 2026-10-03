import pytest

from public_export_support.occurrence_identity import (
    index_events, paired_indexes, identity_key, occurrence_id,
)


def row(identifier=None, year=2026):
    item = {"name": "祭り", "venue": "広場"}
    if identifier is not None:
        item.update(occurrence_id=identifier, event_year=year)
    return item


def test_same_name_multiple_years_and_occurrences_remain_distinct():
    rows = [row("occ_2025", 2025), row("occ_2026a"), row("occ_2026b")]
    assert len(index_events(rows, require_identity=True)) == 3
    assert identity_key(rows[0]) == "occurrence:occ_2025"


def test_legacy_bridge_requires_unique_alias_and_never_bridges_different_ids():
    left, right = paired_indexes([row("occ_a")], [row()])
    assert set(left) == set(right) == {"occurrence:occ_a"}
    left, right = paired_indexes([row("occ_a")], [row("occ_b")])
    assert set(left).isdisjoint(right)
    with pytest.raises(ValueError, match="ambiguous"):
        paired_indexes([row("occ_a"), row("occ_b", 2025)], [row()])


def test_duplicate_identity_and_missing_production_metadata_refuse():
    for rows in ([row(), row()], [row("occ_a"), row("occ_a", 2025)]):
        with pytest.raises(ValueError, match="duplicate"):
            index_events(rows)
    with pytest.raises(ValueError, match="occurrence_id is required"):
        index_events([row()], require_identity=True)
    with pytest.raises(ValueError, match="event_year is required"):
        index_events([{"occurrence_id": "occ_a"}], require_identity=True)


def test_legacy_bridge_never_overwrites_an_existing_identity_on_either_side():
    identified = row("occ_a")
    existing_other_alias = dict(identified, name="別名", venue="別会場")
    for left, right in (([identified], [row(), existing_other_alias]),
                        ([row(), existing_other_alias], [identified])):
        with pytest.raises(ValueError, match="would overwrite"):
            paired_indexes(left, right)


@pytest.mark.parametrize("identifier", [None, "", True, 5, "a b", "a||b"])
def test_invalid_explicit_identity_never_falls_back(identifier):
    with pytest.raises(ValueError, match="invalid occurrence_id"):
        occurrence_id({"occurrence_id": identifier})


@pytest.mark.parametrize("year", [True, "2026", 0, 10000, None])
def test_invalid_year_refuses(year):
    with pytest.raises(ValueError, match="invalid event_year"):
        index_events([row("occ_a", year)], require_identity=True)


def test_internal_identity_is_explicitly_opted_in():
    item = {"name": "祭り", "venue": "広場", "_occurrence_id": "occ_a", "_event_year": 2025}
    assert occurrence_id(item) is None
    assert identity_key(item, include_internal=True) == "occurrence:occ_a"
    assert len(index_events([item], include_internal=True, require_identity=True)) == 1
