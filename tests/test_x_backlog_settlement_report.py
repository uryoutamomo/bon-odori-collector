from build_x_backlog_settlement_report import build

def test_report_is_dry_run_and_separates_high_score_recheck():
    report=build({'items':[{'confidence_score':55},{'confidence_score':49},{'confidence_score':60,'notion_page_id':'done'}]},{'items':[{'status':'pending','time_scope':'future'}]},{'items':[{},{}]})
    assert report['mode']=='dry_run_no_mutation'
    assert report['queues']['event_candidate_queue']['re_evaluate']==1
    assert report['queues']['event_candidate_queue']['archive_after_review']==1
    assert report['queues']['event_candidate_queue']['processed_total']==1
    assert report['queues']['poster_ocr_queue']['retain_daily_cap']==2
