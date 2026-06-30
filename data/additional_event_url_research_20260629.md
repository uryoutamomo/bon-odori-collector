# Additional event URL research

- generated_at: 2026-06-29T12:59:00+00:00
- generated_by: おと（Codex）
- scope: follow-up URL research after missing occurrence and series source URLs were filled
- writes_applied: master RDB event_series.source_url inheritance only
- public_json_applied: false

## Master RDB follow-up

`event_occurrences.source_url` and `event_series.source_url` are now both fully populated.

| table | missing source_url count |
| --- | ---: |
| event_occurrences | 0 |
| event_series | 0 |

## Additional public/official URL candidates

These are candidates for the public official URL gap queue. They were not applied to public JSON in this pass.

| confidence | event | current public date | candidate URL | source type | note |
| --- | --- | --- | --- | --- | --- |
| high | 第25回 四谷納涼踊り大会 / 四谷納涼踊り大会 | 2025-07-19 to 2025-07-20 | https://www.yotsuya3.jp/2025yotsuya-bon-odori/ | organizer/current-year-2025 | 四谷三丁目商店街 page confirms 2025 dates and 四谷ひろば venue. |
| high | 第26回 四谷納涼踊り大会 | 2026-07-18 to 2026-07-19 | https://shinjuku-kushoren.jp/event/event_20260618_5/ | official/current-year-2026 | 新宿区商店会連合会 page confirms 2026 dates and 四谷ひろば venue; useful if promoting this event to 2026. |
| medium | 地域のふれあい第37回盆踊り大会 / 目黒駅前地域ふれあい盆踊り大会 | 2025-07-27 | https://meguromag.jp/event/meguro-bonodiri.html | local-media-current-year-2025 | Page confirms 第39回, 2025-07-27, JR目黒駅西口駅前. Not official. |
| high | 第90回 祐天寺み魂まつり こども盆踊り大会 | 2025-07-16 to 2025-07-18 | https://www.chokai.info/areanews/019220.php | community-info-current-year-2025 | Page confirms 第90回, 令和7年7月16日-18日, 盆踊り time, 祐天寺境内, and organizer. |
| high | 砧小学校「第38回砧っ子夏祭り」 | 2025-07-19 | https://school.setagaya.ed.jp/kita/weblog/104972635 | official-school-retrospective-2025 | 世田谷区立砧小学校 official diary confirms 第38回砧っ子夏祭り on 2025-07-19. |

## Notes

- The four candidates above came from the `expected_high` section of `data/july_official_url_gap_report.md`.
- 四谷 has both a 2025 page matching the current public date and a 2026 page for the next occurrence.
- 目黒駅前 has a useful 2025 URL, but it is not official. Treat it as a web evidence URL unless an organizer/商店街 source is found later.
