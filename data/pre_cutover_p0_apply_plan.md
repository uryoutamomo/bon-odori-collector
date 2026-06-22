# Pre-cutover P0 apply plan

- generated_at: 2026-06-22T14:04:00.194852+00:00
- source_queue: `data/registered_event_investigation_queue.json`
- source_master_db: `data/bon_odori_master.sqlite`
- p0_task_count: 11
- by_bucket: {'historical_reference_recorded': 8, 'keep_investigation_queue': 3}
- human_review_required_count: 7

## Current 2026 Apply Candidates

| event | proposed date | proposed venue | action | review | source |
| --- | --- | --- | --- | --- | --- |

## Historical Reference Only

| event | historical date | historical venue | action | review | source |
| --- | --- | --- | --- | --- | --- |

## Historical References Already Recorded

| event | historical date | historical venue | source |
| --- | --- | --- | --- |
| 濱町音頭盆踊り大会 | 2025-09-27 | 浜町公園中央広場 | https://tokyofesta.com/23ku/25652/ |
| 銀座一丁目東町会・新富町会 納涼盆踊り大会 | 2025-07-19 | 京橋プラザ | https://www.chuo-kanko.or.jp/pages/other_details/115655 |
| ゐの市盆踊り～不忍夢～ | 2025-08-09 to 2025-08-11 | 上野恩賜公園 | https://www.uenopark.info/2025/inoichi-bonodori-2025/ |
| 京橋盆踊り | 2025-08-29 to 2025-08-30 | 京橋中央ひろば（ガレリア） | https://www.edogrand.tokyo/event/6924 |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 2025-08-23 to 2025-08-24 | 新宿中央公園 ファンモアタイムひろば | https://tokyofesta.com/23ku/24845/ |
| 森下二丁目盆踊り | 2025-07-19 to 2025-07-20 | 森下公園 | https://minamisuna1.com/26743/ |
| 赤坂夏おどり（旧 赤坂盆踊り） | 2025-08-29 to 2025-08-30 | TBS赤坂サカス広場 | https://sacas.tokyoevent.net/natsuodori.html |
| 都の辰巳深川 臨海ぼんおどり | 2025-07-19 | 臨海小学校校庭 | https://minamisuna1.com/26743/ |

## Keep In Investigation Queue

| event | action | review | checked | source | note |
| --- | --- | --- | --- | --- | --- |
| 増上寺 地蔵尊盆踊り大会 | keep_as_date_research_task |  | 2026-06-22 | https://www.zojoji.or.jp/event/ev_bonodori.html | Official annual page was rechecked: it confirms the event name and directs inquiries to 安国殿, but still does not publish a usable 2026 date. |
| 旗岡八幡神社例大祭 | keep_as_date_research_task |  | 2026-06-22 | https://hatagaokahachiman-jinja.jp/ | Homepage was rechecked: latest visible festival news remains 令和7年/2025例大祭 material, with no usable 2026 date or bon-odori row. |
| 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！ | source_specific_follow_up |  | 2026-06-22 | https://minato-bon-odori.blogspot.com/ | Current 東京内外の盆踊りマップ upcoming-all page was rechecked and did not expose 盆☆Dance/横川小学校; keep as source-specific follow-up. |

## Write Policy

- notion_write: do_not_write_before_dual_write_boundary_or_explicit_go
- public_json_write: do_not_deploy; local review only
- historical_dates: never_copy_historical_dates_as_2026_confirmed_dates
