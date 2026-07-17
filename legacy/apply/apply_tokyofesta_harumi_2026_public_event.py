"""Promote the 2026 Harumi Pier Park bon-odori event."""

from pathlib import Path

import apply_tokyofesta_2026_public_events_batch as base


base.REPORT_JSON = Path("data/tokyofesta_harumi_2026_public_event_apply_report.json")
base.REPORT_MD = Path("data/tokyofesta_harumi_2026_public_event_apply_report.md")
base.REPORT_TITLE = "TokyoFesta Harumi 2026 public event apply report"

base.EVENTS = [
    {
        "event_name": "第2回 晴海ふ頭公園盆踊り大会",
        "series_id": "ser_bb6ca998e227da40",
        "series_name": "晴海ふ頭公園盆踊り大会",
        "venue_id": "ven_81bb363c51d52347",
        "venue_aliases": ["晴海ふ頭公園"],
        "area": "中央区",
        "date_start": "2026-07-11",
        "date_end": "2026-07-12",
        "source_url": "https://tokyofesta.com/23ku/30964/",
        "public_intro": "晴海ふ頭公園で開かれる、海辺の盆踊り大会。",
        "detail": "2026年イベント掲載で、2026年7月11日(土)〜12日(日)16:00〜21:00、盆踊り18:30〜20:30予定、会場: 晴海ふ頭公園、主催: HARUMI FLAG自治会 / 東部地区公園グループ、共催: HARUMI FLAG CLUB / 晴海テラス自治会を確認。曲目として、これがお江戸の盆ダンス、東京音頭、ダンシング・ヒーロー、きよしのズンドコ節、銀座カンカン娘、炭坑節、どんとこいブギ！、河内おとこ節、東京五輪音頭2020、Let’s ONDO Again の掲載あり。関連URL: https://www.harumiflag.org/",
    },
]


if __name__ == "__main__":
    base.main()
