import copy
import sqlite3

import pytest

from scripts.verify_official_source_link_projection import verify_event_rows


def source_db(tmp_path, *, kind="official_current_year", url="https://official.example/2026", year=2026):
    path = tmp_path / "master.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE event_occurrences (occurrence_id TEXT PRIMARY KEY, event_year INTEGER, date_start TEXT, date_end TEXT, source_kind TEXT, source_url TEXT)")
    connection.execute("INSERT INTO event_occurrences VALUES (?, ?, ?, ?, ?, ?)", ("occ_a", year, "", "", kind, url))
    connection.commit(); connection.close()
    return path


def rows():
    old = {"name": "盆踊り", "venue": "広場", "occurrence_id": "occ_a", "event_year": 2026,
           "detail": "unchanged", "source_urls": [{"label": "旧公式", "url": "https://old.example", "kind": "official"}, {"label": "案内", "url": "https://note.example", "kind": "note"}]}
    new = {**old, "source_urls": [{"label": "公式告知あり", "url": "https://official.example/2026", "kind": "official"}, old["source_urls"][1]]}
    mapping = {"rows": [{"occurrence_id": "occ_a", "event_year": 2026, "public_event_key": "盆踊り|広場||"}]}
    return [old], [new], mapping


def reviewed():
    return {"occ_a": {"event_year": 2026, "date_start": "", "date_end": "", "source_url": "https://official.example/2026"}}


def test_accepts_one_db_bound_official_promotion(tmp_path):
    old, new, mapping = rows()
    changes = verify_event_rows(old, new, mapping, source_db(tmp_path), reviewed())
    assert changes == [{"index": 0, "occurrence_id": "occ_a", "event_year": 2026,
                        "old": old[0]["source_urls"], "new": new[0]["source_urls"],
                        "url": "https://official.example/2026", "kind": "official_current_year", "replacement": "old_official"}]


def reviewed():
    return {"occ_a": {"event_year": 2026, "date_start": "", "date_end": "", "source_url": "https://official.example/2026"}}


def test_accepts_same_url_web_or_sole_anonymous_web_replacement(tmp_path):
    old, new, mapping = rows()
    old[0]["source_urls"] = [{"label": "告知HPあり", "url": "https://official.example/2026", "kind": "web", "count": 1}]
    new[0]["source_urls"] = [{"label": "公式告知あり", "url": "https://official.example/2026", "kind": "official"}]
    database = source_db(tmp_path)
    changes = verify_event_rows(old, new, mapping, database, reviewed())
    assert changes[0]["replacement"] == "same_url_web"
    old[0]["source_urls"] = [{"label": "告知HPあり", "url": "", "kind": "web", "count": 1}]
    changes = verify_event_rows(old, new, mapping, database, reviewed())
    assert changes[0]["replacement"] == "sole_anonymous_web"


def test_same_url_web_promotion_preserves_other_nonofficial_evidence(tmp_path):
    old, new, mapping = rows()
    old[0]["source_urls"] = [{"label": "告知HPあり", "url": "https://official.example/2026", "kind": "web", "count": 1}, {"label": "案内", "url": "https://note.example", "kind": "note"}]
    new[0]["source_urls"] = [{"label": "公式告知あり", "url": "https://official.example/2026", "kind": "official"}, old[0]["source_urls"][1]]
    assert verify_event_rows(old, new, mapping, source_db(tmp_path), reviewed())[0]["replacement"] == "same_url_web"


def test_exact_reviewed_kind_correction_allows_only_listed_payload(tmp_path):
    old, new, mapping = rows()
    old[0]["source_urls"] = [{"label": "告知投稿あり", "url": "https://official.example/2026", "kind": "post", "count": 1}]
    new[0]["source_urls"] = [{"label": "告知HPあり", "url": "https://official.example/2026", "kind": "web", "count": 1}]
    correction = {"occ_a": {"occurrence_id": "occ_a", "event_year": 2026, "source_kind": "official_current_year", "source_url": "https://official.example/2026", "old_source_urls": old[0]["source_urls"], "new_source_urls": new[0]["source_urls"], "reason": "fixture"}}
    assert verify_event_rows(old, new, mapping, source_db(tmp_path), {}, correction)[0]["replacement"] == "reviewed_source_kind_correction"


def test_refuses_multiple_anonymous_web_fallback_replacement(tmp_path):
    old, new, mapping = rows()
    old[0]["source_urls"] = [{"label": "告知HPあり", "url": "", "kind": "web", "count": 2}]
    with pytest.raises(ValueError, match="non-official"):
        verify_event_rows(old, new, mapping, source_db(tmp_path), reviewed())


@pytest.mark.parametrize("mutation", ["detail", "non_official", "wrong_url", "wrong_kind", "wrong_year", "duplicate_map"])
def test_refuses_all_unbound_or_non_source_changes(tmp_path, mutation):
    old, new, mapping = rows(); new, mapping = copy.deepcopy(new), copy.deepcopy(mapping)
    if mutation == "detail": new[0]["detail"] = "changed"
    elif mutation == "non_official": new[0]["source_urls"][1]["url"] = "https://mutated.example"
    elif mutation == "wrong_url": new[0]["source_urls"][0]["url"] = "https://arbitrary.example"
    elif mutation == "wrong_kind":
        db = source_db(tmp_path, kind="organizer_current_year")
        with pytest.raises(ValueError): verify_event_rows(old, new, mapping, db)
        return
    elif mutation == "wrong_year": mapping["rows"][0]["event_year"] = 2025
    else: mapping["rows"].append(copy.deepcopy(mapping["rows"][0]))
    with pytest.raises(ValueError): verify_event_rows(old, new, mapping, source_db(tmp_path), reviewed())


def test_none_public_end_matches_empty_review_and_db(tmp_path):
    old, new, mapping = rows(); old[0]["date_end"] = new[0]["date_end"] = None
    assert verify_event_rows(old, new, mapping, source_db(tmp_path), reviewed())

def test_old_official_plus_anonymous_web_must_not_drop_anonymous(tmp_path):
    old, new, mapping = rows()
    old[0]["source_urls"] = [{"label":"旧","url":"https://old","kind":"official"},{"label":"案内","url":"","kind":"web","count":1}]
    new[0]["source_urls"] = [{"label":"公式告知あり","url":"https://official.example/2026","kind":"official"}]
    with pytest.raises(ValueError, match="non-official"):
        verify_event_rows(old, new, mapping, source_db(tmp_path), reviewed())

def test_wrong_correction_year_is_rejected(tmp_path):
    old, new, mapping = rows(); correction={"occ_a":{"occurrence_id":"occ_a","event_year":2025,"source_kind":"official_current_year","source_url":"https://official.example/2026","old_source_urls":old[0]["source_urls"],"new_source_urls":new[0]["source_urls"],"reason":"x"}}
    with pytest.raises(ValueError): verify_event_rows(old,new,mapping,source_db(tmp_path),{},correction)
