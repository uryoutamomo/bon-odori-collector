from promote_event_dates import build_candidates, parse_dates


def test_parse_explicit_year_range():
    text = "第79回築地本願寺納涼盆踊り大会 2026年7月29日（水）〜8月1日（土）開催"
    assert parse_dates(text) == [
        {
            "start": "2026-07-29",
            "end": "2026-08-01",
            "explicit_year": True,
            "raw": "2026年7月29日（水）〜8月1日",
        }
    ]


def test_parse_same_month_range_with_second_day_only():
    text = "8/21（金）、22日(土)の午後4時から浜町公園にて。"
    assert parse_dates(text, spoken_year=2026) == [
        {
            "start": "2026-08-21",
            "end": "2026-08-22",
            "explicit_year": False,
            "raw": "8/21（金）、22",
        }
    ]


def test_parse_dates_ignores_time_ranges():
    text = "6/27土 16:30-17:30・18:30-19:30 上野恩賜公園"
    assert parse_dates(text, spoken_year=2026) == [
        {
            "start": "2026-06-27",
            "end": None,
            "explicit_year": False,
            "raw": "6/27",
        }
    ]


def test_blog_row_candidate_uses_date_text_not_posted_date():
    events = [
        {
            "id": "event-1",
            "name": "みたままつり 納涼民踊のつどい",
            "venues": ["靖国神社"],
            "date": {},
            "status": "未確認",
            "detail": "",
            "url": "",
        }
    ]
    voices = [
        {
            "source": "blog_row",
            "account": "東京盆踊りマップ",
            "date_hint_text": "7/13〜16",
            "text": "7/13〜16\n靖国神社\nみたままつり 納涼民踊のつどい (6/9夜掲)",
            "url": "https://example.test/detail",
        }
    ]

    candidates = build_candidates(events, voices)

    assert len(candidates) == 1
    assert candidates[0]["new_date"] == "2026-07-13"
    assert candidates[0]["new_date_end"] == "2026-07-16"
    assert candidates[0]["source"] == "blog_row"


def test_generic_sakura_event_name_requires_venue_match():
    events = [
        {
            "id": "event-1",
            "name": "桜まつり",
            "venues": ["三田松坂児童遊園"],
            "date": {},
            "status": "未確認",
            "detail": "",
            "url": "",
        }
    ]
    voices = [
        {
            "source": "blog_row",
            "account": "東京盆踊りマップ",
            "date_hint_text": "3/28",
            "text": "3/28\n新井薬師公園\n新井町会連合会・中野通り桜まつり実行委員会「中野通り桜まつり」開催。",
            "url": "https://example.test/sakura",
        }
    ]

    assert build_candidates(events, voices) == []


def test_generic_extracted_bon_odori_name_does_not_match_specific_event():
    events = [
        {
            "id": "event-1",
            "name": "第2回 大盆踊り祭 with 坂崎守寛",
            "venues": ["日本橋社会教育会館"],
            "date": {"start": "2026-02-21"},
            "status": "確認済み",
            "detail": "",
            "url": "",
        }
    ]
    voices = [
        {
            "source": "blog_row",
            "account": "東京盆踊りマップ",
            "date_hint_text": "6/9",
            "text": "6/9\n日本橋社会教育会館付近\n「和桜会(中央) 第1回 盆踊り練習会」6月9日(火)19:30-20:30。",
            "url": "https://example.test/practice",
        }
    ]

    assert build_candidates(events, voices) == []
