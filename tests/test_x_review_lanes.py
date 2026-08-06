from build_x_review_lanes import build

def row(key, *, official=False, kind='missing_date', known=True):
    return {'source_key':key,'priority_score':10,'candidate_kind':kind,'date_hints':['7月30日'],'matched_occurrence':{'occurrence_id':'occ_x'} if known else None,'source_officiality':{'classification':'registered_official_social' if official else 'unknown'}}

def test_lane1_only_allows_official_known_missing_date_without_overwrite():
    data=build({'candidates':[row('safe',official=True),row('unsafe',official=True,kind='schedule_change')]})
    assert [r['source_key'] for r in data['lanes']['lane1_auto_plan']]==['safe']
    assert [r['source_key'] for r in data['lanes']['lane3_user_review']]==['unsafe']
    assert data['contract']['lane1_no_new_event']

def test_lane3_is_capped_at_three():
    data=build({'candidates':[row(str(i),kind='schedule_change') for i in range(4)]})
    assert len(data['lanes']['lane3_user_review'])==3
    assert len(data['lanes']['lane2_operator_review'])==1

def shibuya_schedule_change(key, text, observed_dates):
    candidate=row(key,kind='schedule_change')
    candidate.update({
        'source_text':text,
        'observed_dates':observed_dates,
        'matched_occurrence':{
            'occurrence_id':'occ_shibuya','event_name':'第7回 渋谷盆踊り','venue':'渋谷109前',
            'date_start':'2026-08-08','date_end':'2026-08-08',
            'detail':'2026年8月8日(土)18:00〜21:30、会場: 渋谷109イベントスペースおよび道玄坂・文化村通り',
        },
    })
    return candidate

def test_lane3_archives_nonasserted_change_when_existing_values_match():
    duplicate=shibuya_schedule_change(
        'duplicate',
        '渋谷盆踊り 2026年8月8日 18:00～21:30 会場：SHIBUYA109前イベントスペース。荒天時は中止となる場合あり',
        ['2026-08-08'],
    )
    data=build({'candidates':[duplicate]})
    assert data['lanes']['lane3_user_review']==[]
    assert data['archived_candidates'][0]['archive_reason']=='existing_schedule_values_match'

def test_lane3_archives_speculative_change_without_schedule_values():
    speculation=shibuya_schedule_change('speculation','渋谷盆踊りは雨で中止になるかもなぁって思ってます',[])
    data=build({'candidates':[speculation]})
    assert data['lanes']['lane3_user_review']==[]
    assert data['archived_candidates'][0]['archive_reason']=='non_asserted_schedule_change'

def test_lane3_keeps_asserted_cancellation_even_when_values_match():
    cancellation=shibuya_schedule_change(
        'cancelled',
        '渋谷盆踊り 2026年8月8日 18:00～21:30 会場：渋谷109前。本日の開催は中止となりました',
        ['2026-08-08'],
    )
    data=build({'candidates':[cancellation]})
    assert [row['source_key'] for row in data['lanes']['lane3_user_review']]==['cancelled']
    assert data['archived_candidates']==[]
