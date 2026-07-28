import sqlite3

from datetime import date
from build_x_gap_candidates import build
from review_inbox_adapters.source_adapter import adapt_source_payload
from review_inbox_adapters.x_gap_adapter import XGapAdapter
from review_inbox_adapters.build_change_requests_from_review_inbox import build_requests


def make_db(path):
    conn=sqlite3.connect(path)
    conn.executescript('''
      CREATE TABLE event_series(series_id TEXT, canonical_name TEXT, area TEXT);
      CREATE TABLE venues(venue_id TEXT, canonical_name TEXT);
      CREATE TABLE event_occurrences(occurrence_id TEXT, series_id TEXT, event_year INTEGER, display_name TEXT, venue_id TEXT, date_start TEXT);
      CREATE TABLE event_series_aliases(series_id TEXT, alias TEXT);
    ''')
    conn.execute("INSERT INTO event_series VALUES ('s1','盆助祭','江東区')")
    conn.execute("INSERT INTO venues VALUES ('v1','音頭公園')")
    conn.execute("INSERT INTO event_occurrences VALUES ('occ1','s1',2026,'盆助祭','v1','')")
    conn.execute("INSERT INTO event_series_aliases VALUES ('s1','Bonsuke Bon')")
    conn.commit(); conn.close()


def test_gap_queue_prefers_missing_date_alias_and_stays_bounded(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    voices=[{"source":"x","tweet_id":str(i),"date":"2026-07-20T00:00:00Z","url":f"https://x.com/a/status/{i}","text":"Bonsuke Bon 7月30日 開催 盆踊り"} for i in range(40)]
    payload=build(voices,db,year=2026,limit=30)
    assert payload['candidate_count']==30
    assert payload['archived_count']==10
    assert payload['candidates'][0]['candidate_kind']=='missing_date'
    assert payload['candidates'][0]['matched_occurrence']['occurrence_id']=='occ1'


def test_old_cancellation_is_not_current_schedule_warning(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    payload=build([{"source":"x","tweet_id":"1","date":"2020-05-01","text":"盆助祭 盆踊りは中止"}],db,year=2026)
    assert payload['candidates']==[]


def test_adapter_explicitly_marks_x_gap_as_future():
    row={"source_key":"x:123","candidate_kind":"missing_date","priority_score":200,"event_year":2026,"source_url":"https://x.com/a/status/123","source_text":"盆助祭 7月30日","date_hints":["7月30日"],"matched_occurrence":{"occurrence_id":"occ_1","event_name":"盆助祭","venue":"音頭公園"}}
    item=adapt_source_payload(XGapAdapter(),{"candidates":[row]})[0]
    assert item['time_scope']=='future'
    assert item['recommended_action']=='confirm_current_year_date'
    requests, unresolved=build_requests([{"source_item":item,"change_type":"confirm_current_year_date"}],current_year=2026)
    assert not unresolved
    assert requests[0]['occurrence_id']=='occ_1'
    assert requests[0]['date_start']=='2026-07-30'


def test_generic_event_name_and_conditional_cancellation_do_not_consume_queue(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    # Add the historically problematic generic series.  It must not match an
    # unrelated post merely because both contain "盆踊り大会".
    conn=sqlite3.connect(db)
    conn.execute("INSERT INTO event_series VALUES ('s2','盆踊り大会','江東区')")
    conn.execute("INSERT INTO event_occurrences VALUES ('occ_2','s2',2026,'盆踊り大会','v1','')")
    conn.commit();conn.close()
    voices=[{"source":"x","tweet_id":"1","date":"2026-07-20","text":"巣鴨盆踊り大会。雨天決行、順延はございません。"}]
    assert build(voices,db,year=2026)['candidates']==[]


def test_overflow_is_retained_as_archive_records(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    voices=[{"source":"x","tweet_id":str(i),"date":"2026-07-20","text":"Bonsuke Bon 7月30日 盆踊り"} for i in range(2)]
    payload=build(voices,db,year=2026,limit=1)
    assert payload['archived_count']==1
    assert len(payload['archived_candidates'])==1


def test_past_occurrence_explicit_prior_year_and_kobe_are_excluded(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    conn=sqlite3.connect(db)
    conn.execute("UPDATE event_occurrences SET date_start='2026-06-27' WHERE occurrence_id='occ1'")
    conn.commit();conn.close()
    old={"source":"x","tweet_id":"old","date":"2026-07-01","text":"盆助祭は本日中止となりました"}
    prior={"source":"x","tweet_id":"prior","date":"2026-07-20","text":"2025年8月2日に盆助祭を開催しました"}
    kobe={"source":"x","tweet_id":"kobe","date":"2026-07-20","text":"神戸市東灘区の盆助祭 7月30日"}
    assert build([old,prior,kobe],db,year=2026,today=date(2026,7,29))['candidates']==[]


def test_official_new_event_is_capped_and_requires_venue_signal(tmp_path, monkeypatch):
    db=tmp_path/'master.sqlite'; make_db(db)
    monkeypatch.setattr('build_x_gap_candidates.assess_source_officiality', lambda *_args, **_kwargs: {'classification':'registered_official_social'})
    voices=[{'source':'x','tweet_id':str(i),'date':'2026-07-20','text':f'夏まつり 7月{i+1}日 会場は駅前広場'} for i in range(8)]
    payload=build(voices,db,year=2026)
    assert len([r for r in payload['candidates'] if r['candidate_kind']=='official_new_event'])==5
    assert payload['archived_count']==3
    no_venue=build([{'source':'x','tweet_id':'x','date':'2026-07-20','text':'夏まつり 7月30日開催'}],db,year=2026)
    assert no_venue['candidates']==[]
