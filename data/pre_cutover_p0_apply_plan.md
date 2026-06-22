# Pre-cutover P0 apply plan

- generated_at: 2026-06-21T02:53:12.490405+00:00
- source_queue: `data/registered_event_investigation_queue.json`
- p0_task_count: 14
- by_bucket: {'historical_reference_only': 8, 'current_2026_apply_candidate': 3, 'keep_investigation_queue': 3}
- human_review_required_count: 9

## Current 2026 Apply Candidates

| event | proposed date | proposed venue | action | review | source |
| --- | --- | --- | --- | --- | --- |
| 品川区民まつり 品川第二地区 | 2026-07-25 to 2026-07-26 | 天妙国寺境内 | review_then_apply_split_or_venue_correction | yes | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html |
| 品川区民まつり 荏原第一地区 | 2026-10-10 | 小山台小学校 | apply_current_2026_date_after_dual_write_ready |  | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html |
| 品川区民まつり 荏原第五地区 | 2026-07-18 to 2026-07-19 | 杜松ホーム | apply_current_2026_date_and_review_venue_name | yes | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html |

## Historical Reference Only

| event | historical date | historical venue | action | review | source |
| --- | --- | --- | --- | --- | --- |
| 濱町音頭盆踊り大会 | 2025-09-27 | 浜町公園中央広場 | promote_2025_historical_reference_only | yes | https://tokyofesta.com/23ku/25652/ |
| 銀座一丁目東町会・新富町会 納涼盆踊り大会 | 2025-07-19 | 京橋プラザ | review_then_promote_2025_historical_reference_only | yes | https://www.chuo-kanko.or.jp/pages/other_details/115655 |
| ゐの市盆踊り～不忍夢～ | 2025-08-09 to 2025-08-11 | 上野恩賜公園 | promote_2025_historical_reference_only | yes | https://www.uenopark.info/2025/inoichi-bonodori-2025/ |
| 京橋盆踊り | 2025-08-29 to 2025-08-30 | 京橋中央ひろば（ガレリア） | promote_2025_historical_reference_only |  | https://www.edogrand.tokyo/event/6924 |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 2025-08-23 to 2025-08-24 | 新宿中央公園 ファンモアタイムひろば | promote_2025_historical_reference_only | yes | https://tokyofesta.com/23ku/24845/ |
| 森下二丁目盆踊り | 2025-07-19 to 2025-07-20 | 森下公園 | keep_2026_unknown_and_promote_2025_historical_reference_only | yes | https://minamisuna1.com/26743/ |
| 赤坂夏おどり（旧 赤坂盆踊り） | 2025-08-29 to 2025-08-30 | TBS赤坂サカス広場 | promote_2025_historical_reference_only | yes | https://sacas.tokyoevent.net/natsuodori.html |
| 都の辰巳深川 臨海ぼんおどり | 2025-07-19 | 臨海小学校校庭 | keep_2026_unknown_and_promote_2025_historical_reference_only | yes | https://minamisuna1.com/26743/ |

## Keep In Investigation Queue

| event | action | review | source | note |
| --- | --- | --- | --- | --- |
| 増上寺 地蔵尊盆踊り大会 | keep_as_date_research_task |  | https://www.zojoji.or.jp/event/ev_bonodori.html | Official annual page confirms the event name but not a usable current-year date. |
| 旗岡八幡神社例大祭 | keep_as_date_research_task |  | https://hatagaokahachiman-jinja.jp/ | Homepage did not expose a usable 2026 date or bon-odori row in the previous pass. |
| 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！ | source_specific_follow_up |  | https://minato-bon-odori.blogspot.com/ | Index/map source needs a specific row follow-up. |

## Write Policy

- notion_write: do_not_write_before_dual_write_boundary_or_explicit_go
- public_json_write: do_not_deploy; local review only
- historical_dates: never_copy_historical_dates_as_2026_confirmed_dates
