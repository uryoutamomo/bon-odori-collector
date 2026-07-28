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
