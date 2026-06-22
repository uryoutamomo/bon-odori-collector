# Notion snapshot -> master drift report

- generated_at: 2026-06-22T15:02:17.462942+00:00
- status: review_required
- master_db: `data/bon_odori_master.sqlite`
- notion_db: `data/notion_snapshot.sqlite`
- diff_count: 32
- linked_counts: {'notion_venues_linked': 213, 'notion_events_linked': 222, 'notion_songs_linked': 141}
- notion_counts: {'notion_venues': 213, 'notion_events': 222, 'notion_songs': 141}

## Diffs by entity

- event_occurrence: 24
- event_series: 8

## Diffs by field

- event_occurrence.date_end: 2
- event_occurrence.date_start: 5
- event_occurrence.date_status: 6
- event_occurrence.lifecycle_status: 1
- event_occurrence.source_url: 4
- event_occurrence.venue_id: 6
- event_series.public_intro: 1
- event_series.source_url: 2
- event_series.usual_venue_id: 5

## Diffs by kind

- master_has_value_notion_empty: 19
- notion_has_value_master_empty: 1
- value_conflict: 12

## Diff detail

| entity | title | field | kind | recommendation | master | notion snapshot |
| --- | --- | --- | --- | --- | --- | --- |
| event_occurrence | 新橋こいち祭 | venue_id | master_has_value_notion_empty | preserve_master | ven_331b917a98238b0d |  |
| event_occurrence | 新橋こいち祭 | date_status | value_conflict | review_conflict | confirmed | predicted |
| event_occurrence | 新橋こいち祭 | lifecycle_status | value_conflict | review_conflict | published | 未確認 |
| event_occurrence | 新橋こいち祭 | source_url | value_conflict | review_conflict | http://www.shinbashi.net/top/koichi/2026/greeting/ | http://www.shinbashi.net/top/koichi/ |
| event_occurrence | 中野駅前大盆踊り大会 | venue_id | master_has_value_notion_empty | preserve_master | ven_c1a0d7dbd4fae8d5 |  |
| event_occurrence | 中野駅前大盆踊り大会 | date_start | master_has_value_notion_empty | preserve_master | 2026-08-01 |  |
| event_occurrence | 中野駅前大盆踊り大会 | date_end | master_has_value_notion_empty | preserve_master | 2026-08-02 |  |
| event_occurrence | 中野駅前大盆踊り大会 | date_status | value_conflict | review_conflict | confirmed | unknown |
| event_occurrence | マロニエまつり盆踊り大会 | venue_id | master_has_value_notion_empty | preserve_master | ven_e82a2aed94e45d29 |  |
| event_occurrence | マロニエまつり盆踊り大会 | source_url | master_has_value_notion_empty | preserve_master | https://x.com/1205uzonke/status/2065200648086487508 |  |
| event_occurrence | 雷門盆踊り（浅草） | source_url | master_has_value_notion_empty | preserve_master | https://x.com/STBA_Bonodori/status/2059220925862883623 |  |
| event_occurrence | 藤沢七夕まつり（DJ盆踊り大会） | venue_id | master_has_value_notion_empty | preserve_master | ven_61c6063cf53195b5 |  |
| event_occurrence | 郡上おどり in 青山 | venue_id | master_has_value_notion_empty | preserve_master | ven_a52431fddb1891f8 |  |
| event_occurrence | 品川区民まつり 荏原第五地区 | venue_id | value_conflict | review_conflict | ven_a2ba81d51cea787c | ven_3e4793480293aa92 |
| event_occurrence | 品川区民まつり 荏原第五地区 | date_start | master_has_value_notion_empty | preserve_master | 2026-07-18 |  |
| event_occurrence | 品川区民まつり 荏原第五地区 | date_end | master_has_value_notion_empty | preserve_master | 2026-07-19 |  |
| event_occurrence | 品川区民まつり 荏原第五地区 | date_status | value_conflict | review_conflict | confirmed | unknown |
| event_occurrence | 品川区民まつり 荏原第三地区 | date_start | master_has_value_notion_empty | preserve_master | 2026-10-18 |  |
| event_occurrence | 品川区民まつり 荏原第三地区 | date_status | value_conflict | review_conflict | confirmed | unknown |
| event_occurrence | 品川区民まつり 八潮地区 | date_start | master_has_value_notion_empty | preserve_master | 2026-09-20 |  |
| event_occurrence | 品川区民まつり 八潮地区 | date_status | value_conflict | review_conflict | confirmed | unknown |
| event_occurrence | 品川区民まつり 八潮地区 | source_url | value_conflict | review_conflict | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | https://www.city.shinagawa.tokyo.jp/PC/kuseizyoho/kuseizyoho-koho/kuseizyoho-koho-kohoshinagawa/index.html |
| event_occurrence | 品川区民まつり 荏原第四地区 | date_start | master_has_value_notion_empty | preserve_master | 2026-10-11 |  |
| event_occurrence | 品川区民まつり 荏原第四地区 | date_status | value_conflict | review_conflict | confirmed | unknown |
| event_series | 新橋こいち祭 | usual_venue_id | master_has_value_notion_empty | preserve_master | ven_331b917a98238b0d |  |
| event_series | 中野駅前大盆踊り大会 | usual_venue_id | master_has_value_notion_empty | preserve_master | ven_c1a0d7dbd4fae8d5 |  |
| event_series | マロニエまつり盆踊り大会 | usual_venue_id | master_has_value_notion_empty | preserve_master | ven_e82a2aed94e45d29 |  |
| event_series | SHIBUYA MIYASHITA PARK BON DANCE | public_intro | notion_has_value_master_empty | review_before_copy_from_notion |  | 渋谷・宮下公園の芝生の上で開かれる現代型の盆踊り。買い物帰りにふらっと輪に入れる、渋谷らしいボンダンス。 |
| event_series | SHIBUYA MIYASHITA PARK BON DANCE | source_url | value_conflict | review_conflict | https://miyashita-bondance.jp/2025/ | https://mantan-web.jp/prtimes/article/20260527prt00m200000530a.html |
| event_series | 藤沢七夕まつり（DJ盆踊り大会） | usual_venue_id | master_has_value_notion_empty | preserve_master | ven_61c6063cf53195b5 |  |
| event_series | 郡上おどり in 青山 | usual_venue_id | master_has_value_notion_empty | preserve_master | ven_a52431fddb1891f8 |  |
| event_series | 郡上おどり in 青山 | source_url | value_conflict | review_conflict | https://aoyama-gaienmae.or.jp/news/20260326/ | https://aoyama-gaienmae.or.jp/news/20250617/ |
