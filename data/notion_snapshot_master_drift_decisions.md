# Notion snapshot drift decisions

- generated_at: 2026-06-22T15:17:25.074989+00:00
- status: apply_candidates_ready
- source_diff_count: 32
- by_decision: {'candidate_copy_notion_public_intro': 1, 'hold_for_manual_review': 5, 'preserve_master': 19, 'preserve_master_confirmed_state': 7}
- by_apply_readiness: {'apply_ready': 1, 'not_apply_ready': 31}

## Policy

- preserve_master_empty_notion: True
- preserve_reviewed_confirmed_state_over_weaker_notion: True
- copy_notion_public_intro_when_master_empty: candidate_only
- conflicting_source_url_or_venue: hold_for_manual_review

## Decisions

| decision | title | field | apply | reason | master | notion snapshot |
| --- | --- | --- | --- | --- | --- | --- |
| preserve_master | 新橋こいち祭 | venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_331b917a98238b0d |  |
| preserve_master_confirmed_state | 新橋こいち祭 | date_status | no | Master DB already records reviewed confirmed/published state; Notion snapshot is weaker. | confirmed | predicted |
| preserve_master_confirmed_state | 新橋こいち祭 | lifecycle_status | no | Master DB already records reviewed confirmed/published state; Notion snapshot is weaker. | published | 未確認 |
| hold_for_manual_review | 新橋こいち祭 | source_url | no | Conflict needs source review before changing master DB. | http://www.shinbashi.net/top/koichi/2026/greeting/ | http://www.shinbashi.net/top/koichi/ |
| preserve_master | 中野駅前大盆踊り大会 | venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_c1a0d7dbd4fae8d5 |  |
| preserve_master | 中野駅前大盆踊り大会 | date_start | no | Master DB has reviewed value while Notion snapshot is empty. | 2026-08-01 |  |
| preserve_master | 中野駅前大盆踊り大会 | date_end | no | Master DB has reviewed value while Notion snapshot is empty. | 2026-08-02 |  |
| preserve_master_confirmed_state | 中野駅前大盆踊り大会 | date_status | no | Master DB already records reviewed confirmed/published state; Notion snapshot is weaker. | confirmed | unknown |
| preserve_master | マロニエまつり盆踊り大会 | venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_e82a2aed94e45d29 |  |
| preserve_master | マロニエまつり盆踊り大会 | source_url | no | Master DB has reviewed value while Notion snapshot is empty. | https://x.com/1205uzonke/status/2065200648086487508 |  |
| preserve_master | 雷門盆踊り（浅草） | source_url | no | Master DB has reviewed value while Notion snapshot is empty. | https://x.com/STBA_Bonodori/status/2059220925862883623 |  |
| preserve_master | 藤沢七夕まつり（DJ盆踊り大会） | venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_61c6063cf53195b5 |  |
| preserve_master | 郡上おどり in 青山 | venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_a52431fddb1891f8 |  |
| hold_for_manual_review | 品川区民まつり 荏原第五地区 | venue_id | no | Conflict needs source review before changing master DB. | ven_a2ba81d51cea787c | ven_3e4793480293aa92 |
| preserve_master | 品川区民まつり 荏原第五地区 | date_start | no | Master DB has reviewed value while Notion snapshot is empty. | 2026-07-18 |  |
| preserve_master | 品川区民まつり 荏原第五地区 | date_end | no | Master DB has reviewed value while Notion snapshot is empty. | 2026-07-19 |  |
| preserve_master_confirmed_state | 品川区民まつり 荏原第五地区 | date_status | no | Master DB already records reviewed confirmed/published state; Notion snapshot is weaker. | confirmed | unknown |
| preserve_master | 品川区民まつり 荏原第三地区 | date_start | no | Master DB has reviewed value while Notion snapshot is empty. | 2026-10-18 |  |
| preserve_master_confirmed_state | 品川区民まつり 荏原第三地区 | date_status | no | Master DB already records reviewed confirmed/published state; Notion snapshot is weaker. | confirmed | unknown |
| preserve_master | 品川区民まつり 八潮地区 | date_start | no | Master DB has reviewed value while Notion snapshot is empty. | 2026-09-20 |  |
| preserve_master_confirmed_state | 品川区民まつり 八潮地区 | date_status | no | Master DB already records reviewed confirmed/published state; Notion snapshot is weaker. | confirmed | unknown |
| hold_for_manual_review | 品川区民まつり 八潮地区 | source_url | no | Conflict needs source review before changing master DB. | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | https://www.city.shinagawa.tokyo.jp/PC/kuseizyoho/kuseizyoho-koho/kuseizyoho-koho-kohoshinagawa/index.html |
| preserve_master | 品川区民まつり 荏原第四地区 | date_start | no | Master DB has reviewed value while Notion snapshot is empty. | 2026-10-11 |  |
| preserve_master_confirmed_state | 品川区民まつり 荏原第四地区 | date_status | no | Master DB already records reviewed confirmed/published state; Notion snapshot is weaker. | confirmed | unknown |
| preserve_master | 新橋こいち祭 | usual_venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_331b917a98238b0d |  |
| preserve_master | 中野駅前大盆踊り大会 | usual_venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_c1a0d7dbd4fae8d5 |  |
| preserve_master | マロニエまつり盆踊り大会 | usual_venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_e82a2aed94e45d29 |  |
| candidate_copy_notion_public_intro | SHIBUYA MIYASHITA PARK BON DANCE | public_intro | yes | Notion has public_intro text and master is empty; local DB copy is low risk but still separate from Notion/public deploy. |  | 渋谷・宮下公園の芝生の上で開かれる現代型の盆踊り。買い物帰りにふらっと輪に入れる、渋谷らしいボンダンス。 |
| hold_for_manual_review | SHIBUYA MIYASHITA PARK BON DANCE | source_url | no | Conflict needs source review before changing master DB. | https://miyashita-bondance.jp/2025/ | https://mantan-web.jp/prtimes/article/20260527prt00m200000530a.html |
| preserve_master | 藤沢七夕まつり（DJ盆踊り大会） | usual_venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_61c6063cf53195b5 |  |
| preserve_master | 郡上おどり in 青山 | usual_venue_id | no | Master DB has reviewed value while Notion snapshot is empty. | ven_a52431fddb1891f8 |  |
| hold_for_manual_review | 郡上おどり in 青山 | source_url | no | Conflict needs source review before changing master DB. | https://aoyama-gaienmae.or.jp/news/20260326/ | https://aoyama-gaienmae.or.jp/news/20250617/ |
