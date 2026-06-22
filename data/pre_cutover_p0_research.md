# Pre-cutover P0 investigation review

- generated_by: おと（Codex）
- generated_at: 2026-06-21
- source_queue: `data/registered_event_investigation_queue.json`
- scope: `primary_unconfirmed` + `priority_label=P0`
- policy: Notion/public JSON へは未反映。DB移行前の適用候補と、移行後キュー継続対象を分ける。

## Summary

- P0 after quality tightening: 14
- 2026 current official/source update candidates: 3
- 2025 historical-reference candidates: 7
- keep investigation queue / no apply yet: 4

## 2026 current update candidates

These have 2026 dates on a current source and are suitable for review-then-apply after DB dual-write rules are ready.

| event | proposed date | proposed venue | confidence | note | source |
| --- | --- | --- | --- | --- | --- |
| 品川区民まつり 品川第二地区 | 2026-07-25 to 2026-07-26 | 天妙国寺境内 | high | Current Notion venue `城南小学校` points to the child-corner slot, not the bon-odori slot. Needs venue correction or split. | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html |
| 品川区民まつり 荏原第一地区 | 2026-10-10 | 小山台小学校 | high | Single date/venue; straightforward date fill. | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html |
| 品川区民まつり 荏原第五地区 | 2026-07-18 to 2026-07-19 | 杜松ホーム | high | Current Notion venue `旧杜松小学校` should be checked; 2026 source says `杜松ホーム`. | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html |

## Historical-reference candidates only

These have useful 2025 evidence but should not be copied as 2026 dates.

| event | historical date | venue | confidence | next action | source |
| --- | --- | --- | --- | --- | --- |
| 濱町音頭盆踊り大会 | 2025-09-27 | 浜町公園中央広場 | medium | Add as 2025 historical reference; keep 2026 unknown. | https://tokyofesta.com/23ku/25652/ |
| 銀座一丁目東町会・新富町会 納涼盆踊り大会 | 2025-07-19 | 京橋プラザ | medium | Observed evidence is useful; source page itself does not expose the specific row in fetched text. Review before apply. | https://www.chuo-kanko.or.jp/pages/other_details/115655 |
| ゐの市盆踊り～不忍夢～ | 2025-08-09 to 2025-08-11 | 上野恩賜公園 | medium | Historical reference only. | https://www.uenopark.info/2025/inoichi-bonodori-2025/ |
| 京橋盆踊り | 2025-08-29 to 2025-08-30 | 京橋中央ひろば（ガレリア） | high | Historical reference only; source marks the event ended. | https://www.edogrand.tokyo/event/6924 |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 2025-08-23 to 2025-08-24 | 新宿中央公園 ファンモアタイムひろば | medium | Historical reference only. | https://tokyofesta.com/23ku/24845/ |
| 森下二丁目盆踊り | 2025-07-19 to 2025-07-20 | 森下公園 | medium | 2026 latest page currently lacks this row; keep as historical reference. | https://minamisuna1.com/26743/ |
| 赤坂夏おどり（旧 赤坂盆踊り） | 2025-08-29 to 2025-08-30 | TBS赤坂サカス広場 | medium | Historical reference only; 2026 page title is a schedule site but row is 2025. | https://sacas.tokyoevent.net/natsuodori.html |
| 都の辰巳深川 臨海ぼんおどり | 2025-07-19 | 臨海小学校校庭 | medium | 2026 latest page currently lacks this row; keep as historical reference. | https://minamisuna1.com/26743/ |

## Keep in investigation queue

These should not be applied before migration.

| event | reason | next action | source |
| --- | --- | --- | --- |
| 増上寺 地蔵尊盆踊り大会 | Official annual page confirms the event name but does not provide a date. | Keep as date research task. | https://www.zojoji.or.jp/event/ev_bonodori.html |
| 旗岡八幡神社例大祭 | Homepage shows 2025 news, but fetched content does not expose a usable 2026 date/bon-odori row. | Keep as date research task. | https://hatagaokahachiman-jinja.jp/ |
| 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！ | Source is an index/map page; the specific row was not fetched in this pass. | Keep as source-specific follow-up. | https://minato-bon-odori.blogspot.com/ |
| 品川区民まつり 大崎第一地区 | Multiple dates and venues; this is an occurrence-split problem, not a single date fill. | Keep as split/review task, now demoted from P0. | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html |

## Queue tightening applied

- Low-confidence observed candidates no longer add priority by themselves.
- Generic/stale names such as `桜まつり`, `盆踊り大会`, `盆ダンスフェスティバル2023` are not allowed to remain P0.
- Tokyo 23 outside hints are not allowed to remain P0.
- Multi-venue events are treated as occurrence-split tasks and are not allowed to remain P0.
- Archival-only sources such as old `盆まる` venue pages are not allowed to remain P0.
