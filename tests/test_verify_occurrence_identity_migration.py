import copy
import pytest
from scripts.verify_occurrence_identity_migration import verify_event_rows


def inputs():
    old = [{"name": "盆踊り", "venue": "広場", "date": "", "unknown": None}]
    new = [dict(old[0], occurrence_id="occ_a", event_year=2025)]
    sources = {"rows": [{"public_event_key": "盆踊り|広場||", "occurrence_id": "occ_a", "event_year": 2025}]}
    return old, new, sources


def test_migration_accepts_exact_metadata_addition():
    verify_event_rows(*inputs())


@pytest.mark.parametrize("change", ["wrong_id", "wrong_year", "detail", "missing_null", "duplicate", "missing_id"])
def test_migration_refuses_unrelated_change_and_wrong_binding(change):
    old, new, sources = copy.deepcopy(inputs())
    if change == "wrong_id":
        new[0]["occurrence_id"] = "occ_b"
    elif change == "wrong_year":
        new[0]["event_year"] = 2026
    elif change == "detail":
        new[0]["detail"] = "追加"
    elif change == "missing_null":
        del new[0]["unknown"]
    elif change == "duplicate":
        new.append(copy.deepcopy(new[0]))
    else:
        del new[0]["occurrence_id"]
    with pytest.raises(ValueError):
        verify_event_rows(old, new, sources)
