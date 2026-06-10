from promote_event_dates import parse_dates


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
            "raw": "8/21（金）、22日",
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
