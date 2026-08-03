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
      CREATE TABLE event_occurrences(occurrence_id TEXT, series_id TEXT, event_year INTEGER, display_name TEXT, venue_id TEXT, date_start TEXT, date_end TEXT);
      CREATE TABLE event_series_aliases(series_id TEXT, alias TEXT);
    ''')
    conn.execute("INSERT INTO event_series VALUES ('s1','盆助祭','江東区')")
    conn.execute("INSERT INTO venues VALUES ('v1','音頭公園')")
    conn.execute("INSERT INTO event_occurrences VALUES ('occ1','s1',2026,'盆助祭','v1','','')")
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
    conn.execute("INSERT INTO event_occurrences VALUES ('occ_2','s2',2026,'盆踊り大会','v1','','')")
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


def test_informal_new_events_require_future_date_positive_23_scope_and_are_capped(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    voices=[{'source':'x','tweet_id':str(i),'date':'2026-08-01',
             'text':f'北区 十条駅前広場 夏まつり 8/{8+i} 開催'} for i in range(12)]
    # Times, ambiguous locations, and known out-of-scope cities must not open
    # the informal discovery lane.
    voices.extend([
        {'source':'x','tweet_id':'time','date':'2026-08-01','text':'盆踊り 十条駅前広場 18時から'},
        {'source':'x','tweet_id':'unknown','date':'2026-08-01','text':'盆踊り 会場は駅前広場 8/20'},
        {'source':'x','tweet_id':'outside','date':'2026-08-01','text':'大阪北御堂 夏まつり 駅前広場 8/20'},
    ])
    payload=build(voices,db,year=2026,today=date(2026,8,1))
    informal=[row for row in payload['candidates'] if row['candidate_kind']=='informal_new_event']
    assert len(informal)==10
    assert all(row['corroboration_count']==1 for row in informal)
    assert all('大阪' not in row['source_text'] for row in informal)
    assert any(row.get('archive_reason')=='informal_new_event_daily_cap' for row in payload['archived_candidates'])


def test_date_range_conflicts_are_grouped_with_corroborating_sources(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    conn=sqlite3.connect(db)
    conn.execute("UPDATE event_series SET canonical_name='上野ゐの市盆踊り' WHERE series_id='s1'")
    conn.execute("UPDATE event_occurrences SET display_name='上野ゐの市盆踊り', date_start='2026-08-07', date_end='2026-08-09' WHERE occurrence_id='occ1'")
    conn.commit(); conn.close()
    voices=[{'source':'x','tweet_id':str(i),'account':f'@performer{i}','date':'2026-08-01',
             'url':f'https://x.example/{i}',
             'text':'上野ゐの市盆踊り 上野恩賜公園 袴腰広場 2026年8月7日〜8月16日 開催'} for i in range(14)]
    payload=build(voices,db,year=2026,today=date(2026,8,1))
    conflicts=[row for row in payload['candidates'] if row['candidate_kind']=='date_range_conflict']
    assert len(conflicts)==1
    assert conflicts[0]['corroboration_count']==14
    assert conflicts[0]['source_count']==14
    assert len(conflicts[0]['source_urls'])==14
    assert conflicts[0]['matched_occurrence']['occurrence_id']=='occ1'


def test_past_event_reports_are_bounded_and_reject_same_named_outside_wards(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    voices=[{'source':'x','tweet_id':str(i),'date':'2026-08-03',
             'text':f'板橋区 北野小学校の盆踊りに行ってきた 7/{i+1} 楽しかった'} for i in range(12)]
    voices.extend([
        {'source':'x','tweet_id':'yokohama','date':'2026-08-03','text':'横浜市港北区 大曽根小学校の盆踊りに行ってきた 8/2'},
        {'source':'x','tweet_id':'nagoya','date':'2026-08-03','text':'名古屋市北区 東志賀小学校の盆踊りに行ってきた 8/1'},
        {'source':'x','tweet_id':'kyoto','date':'2026-08-03','text':'京都市上京区 桃薗ふれあい夏まつりに参加した 8/2 会場は広場'},
        {'source':'x','tweet_id':'hamamatsu','date':'2026-08-03','text':'横山小学校の盆踊りにお邪魔した 7/18 東京音頭が楽しかった'},
    ])
    payload=build(voices,db,year=2026,today=date(2026,8,4))
    reports=[row for row in payload['candidates'] if row['candidate_kind']=='past_event_report']
    assert len(reports)==10
    assert all('北野小学校' in row['source_text'] for row in reports)
    assert any(row.get('archive_reason')=='past_event_report_daily_cap' for row in payload['archived_candidates'])


def test_multi_venue_past_report_is_archived_for_manual_expansion(tmp_path):
    db=tmp_path/'master.sqlite'; make_db(db)
    voice={'source':'x','tweet_id':'list','date':'2026-07-27',
           'text':'板橋区で7/26に参加しました。蓮根みなみ公園、志村第5小学校、赤塚氷川神社の盆踊り'}
    payload=build([voice],db,year=2026,today=date(2026,8,4))
    assert payload['candidates']==[]
    assert payload['archived_candidates'][0]['archive_reason']=='multiple_venues_requires_manual_expansion'
