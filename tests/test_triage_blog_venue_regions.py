"""Region-aware legacy blog triage; all IO is limited to temporary fixtures."""
import io
import json
import xml.etree.ElementTree as ET

import pytest

import extract_venues_blog as seeds
import extract_blog_venue_rows as structured
import triage_blog_venue_candidates as triage


def run_triage(monkeypatch, tmp_path, candidates, master):
    paths = {key: tmp_path / name for key, name in (
        ("CANDIDATES_FILE", "seed.json"), ("VENUE_MASTER_FILE", "master.json"),
        ("SOURCE_URLS_FILE", "sources.json"), ("OUT_FILE", "triage.json"))}
    paths["CANDIDATES_FILE"].write_text(json.dumps(candidates, ensure_ascii=False))
    paths["VENUE_MASTER_FILE"].write_text(json.dumps(master, ensure_ascii=False))
    paths["SOURCE_URLS_FILE"].write_text(json.dumps({"fixture": "https://example.test/2026"}))
    before = {path: path.read_bytes() for key, path in paths.items() if key != "OUT_FILE"}
    for key, path in paths.items():
        monkeypatch.setattr(triage, key, path)
    triage.main()
    assert all(path.read_bytes() == raw for path, raw in before.items())
    return json.loads(paths["OUT_FILE"].read_text())


def candidate(name="馬橋小学校", region="杉並区"):
    return {"venue": name, "region_hint": region, "source_title": "fixture", "in_tsukiji_30min_guess": False}


@pytest.mark.parametrize("name,master_name,reason", [
    ("馬橋小学校", "馬橋小学校", "exact_match"),
    ("馬橋小学校（会場）", "馬橋小学校", "normalized_match"),
    ("上野公園", "上野恩賜公園", "known_alias"),
    ("上野公園", "上野恩賜公園（噴水前）", "known_alias"),
])
def test_every_name_route_rejects_region_mismatch(monkeypatch, tmp_path, name, master_name, reason):
    report = run_triage(monkeypatch, tmp_path, [candidate(name)], [{"venue": master_name, "region": "松戸市"}])
    row, = report["items"]
    assert row["status"] == "research" and row["reason"] == "region_mismatch"
    assert row["mapped_to"] is None and row["priority"] == "normal"


@pytest.mark.parametrize("name,master_name,status,reason", [
    ("馬橋小学校", "馬橋小学校", "registered", "exact_match"),
    ("馬橋小学校（会場）", "馬橋小学校", "registered_alias", "normalized_match"),
    ("上野公園", "上野恩賜公園", "registered_alias", "known_alias"),
])
def test_same_region_retains_matching_contract(monkeypatch, tmp_path, name, master_name, status, reason):
    row, = run_triage(monkeypatch, tmp_path, [candidate(name)], [{"venue": master_name, "region": "杉並区"}])["items"]
    assert (row["status"], row["reason"], row["mapped_to"], row["priority"]) == (status, reason, master_name, "skip")
    assert row["source_url"] == "https://example.test/2026" and row["region_hint"] == "杉並区"


@pytest.mark.parametrize("source_region,master_region", [
    (None, "杉並区"), ("杉並区", None), (None, None), ("", "杉並区"),
    ("　", "杉並区"), ("不明", "杉並区"), ("東京都", "杉並区"),
])
def test_missing_region_keeps_real_master_match_in_review(monkeypatch, tmp_path, source_region, master_region):
    row, = run_triage(monkeypatch, tmp_path, [candidate(region=source_region)],
                     [{"venue": "馬橋小学校", "region": master_region}])["items"]
    assert row["status"] == "research" and row["reason"] == "region_unknown"
    assert row["mapped_to"] is None and row["priority"] != "skip"


@pytest.mark.parametrize("source_region,master_region", [
    (" 東京都 杉並区　", "杉並区"), ("杉並区", "東京都杉並区"), ("杉並 区", "杉並区"),
])
def test_region_formatting_is_normalized_without_rewriting_input(monkeypatch, tmp_path, source_region, master_region):
    row, = run_triage(monkeypatch, tmp_path, [candidate(region=source_region)],
                     [{"venue": "馬橋小学校", "region": master_region}])["items"]
    assert row["status"] == "registered" and row["region_hint"] == source_region


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_master_names_select_only_a_unique_explicit_region(monkeypatch, tmp_path, reverse):
    master = [{"venue": "馬橋小学校", "region": "杉並区"}, {"venue": "馬橋小学校", "region": "松戸市"}]
    if reverse:
        master.reverse()
    rows = run_triage(monkeypatch, tmp_path, [candidate(), candidate(region="世田谷区")], master)["items"]
    indexed = {row["region_hint"]: row for row in rows}
    assert indexed["杉並区"]["status"] == "registered"
    assert indexed["世田谷区"]["reason"] == "region_mismatch"
    assert indexed["世田谷区"]["priority"] == "high"


@pytest.mark.parametrize("name,master", [
    ("馬橋小学校", [{"venue": "馬橋小学校", "region": "杉並区", "address": "A"},
                   {"venue": "馬橋小学校", "region": "杉並区", "address": "B"}]),
    ("馬橋小学校（会場）", [{"venue": "馬橋小学校", "region": "杉並区"},
                         {"venue": "馬橋小学校広場", "region": "杉並区"}]),
    ("上野公園", [{"venue": "上野恩賜公園（噴水前）", "region": "杉並区"},
                  {"venue": "上野恩賜公園（別会場）", "region": "杉並区"}]),
    ("馬橋小学校", [{"venue": "馬橋小学校", "region": "杉並区"}, {"venue": "馬橋小学校", "region": None}]),
])
def test_ambiguous_master_matches_are_not_arbitrarily_overwritten(monkeypatch, tmp_path, name, master):
    row, = run_triage(monkeypatch, tmp_path, [candidate(name)], master)["items"]
    assert row["status"] == "research" and row["reason"] == "ambiguous_match"
    assert row["mapped_to"] is None


def test_alias_without_master_is_explicitly_outside_this_region_fix(monkeypatch, tmp_path):
    row, = run_triage(monkeypatch, tmp_path, [candidate("上野公園")], [])["items"]
    assert (row["status"], row["reason"], row["mapped_to"]) == ("registered_alias", "known_alias", "上野恩賜公園")


def test_unmatched_and_noise_priority_policy_is_unchanged(monkeypatch, tmp_path):
    rows = run_triage(monkeypatch, tmp_path, [candidate("新しい小学校", "世田谷区"), candidate("会場前広場")], [])["items"]
    assert any(row["status"] == "research" and row["priority"] == "high" for row in rows)
    # Use an actual existing noise token independently of venue matching.
    row, = run_triage(monkeypatch, tmp_path, [candidate("前広場")], [])["items"]
    assert row["status"] == "noise" and row["priority"] == "skip"


def test_fixture_feed_extraction_through_triage_keeps_suginami_collision_for_review(monkeypatch, tmp_path):
    title = "杉並区の盆おどり情報 2026年1月より [Suginami-q]"
    content = ('<table><tr><td>2026 10/31</td><td class="cLoc">馬橋小学校</td>'
               '<td class="cDsc">馬橋盆踊り 10月31日</td><td class="cAdr">杉並区高円寺北4-28</td>'
               '<td><a href="https://example.test/mabashi2026">公式資料</a></td></tr></table>')
    root = ET.Element("feed", xmlns="http://www.w3.org/2005/Atom")
    entry = ET.SubElement(root, "entry")
    ET.SubElement(entry, "title").text = title
    ET.SubElement(entry, "content").text = content
    ET.SubElement(entry, "link", rel="alternate", href="https://example.test/suginami")
    xml = ET.tostring(root)
    monkeypatch.setattr(seeds.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(xml))
    monkeypatch.setattr(seeds, "OUT", str(tmp_path / "extracted-seeds.json"))
    monkeypatch.setattr(structured, "OUT", tmp_path / "extracted-rows.json")
    seeds.main(); structured.main()
    extracted = json.loads((tmp_path / "extracted-seeds.json").read_text())
    selected = [row for row in extracted if row["venue"] == "馬橋小学校"]
    assert len(selected) == 1 and selected[0]["region_hint"] == "杉並区"
    row, = json.loads((tmp_path / "extracted-rows.json").read_text())
    assert "10/31" in row["date_text"] and row["address"] == "杉並区高円寺北4-28"
    result, = run_triage(monkeypatch, tmp_path, selected, [{"venue": "馬橋小学校", "region": "松戸市"}])["items"]
    assert result["status"] == "research" and result["reason"] == "region_mismatch"
    assert result["region_hint"] == "杉並区" and result["mapped_to"] is None
