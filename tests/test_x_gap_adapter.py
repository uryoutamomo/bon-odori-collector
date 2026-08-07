from review_inbox_adapters.x_gap_adapter import XGapAdapter, event_name_guess


def test_informal_event_uses_bracketed_name_as_explicit_guess_for_title():
    row={
        'source_key':'x:1', 'candidate_kind':'informal_new_event', 'source_text':'【大井どんたく夏まつり】\n8/22(土)',
        'source_url':'https://x.com/test/status/1', 'matched_occurrence':None,
    }
    item=XGapAdapter().adapt_row(row)
    assert item['title']=='大井どんたく夏まつり'
    assert item['event_name']==''
    assert item['event_name_guess']=='大井どんたく夏まつり'
    assert item['payload']['event_name_guess']=='大井どんたく夏まつり'


def test_missing_brackets_keeps_existing_text_excerpt_fallback():
    assert event_name_guess('盆踊りのお知らせ')==''


def test_ignores_non_event_brackets_before_the_event_name():
    assert event_name_guess('【20代30代限定】\n【第72回大井どんたく夏まつり】')=='第72回大井どんたく夏まつり'
