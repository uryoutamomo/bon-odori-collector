# July official source promotions

- generated_at: 2026-06-29T16:41:48.280856+00:00
- mode: dry_run
- applied: False
- checked_count: 3
- updated_count: 0
- already_current_count: 3
- backup_db:

| event | changed | before source_kind | after source_kind | source_url | reason |
| --- | --- | --- | --- | --- | --- |
| みたままつり 納涼民踊のつどい | no | official_current_year | official_current_year | https://www.yasukuni.or.jp/schedule/saiji.html#saiji03 | 靖国神社公式の祭事ページで、みたままつり 7月13日〜16日と期間中の盆踊りを確認。 |
| 佐竹ゲバゲバ盆踊り | no | official_current_year | official_current_year | https://satakeshotengai.com/satakeodori/ | 佐竹商店街公式サイトのサタケオドリ専用ページで、2026年7月18日開催と佐竹ゲバゲバ盆踊りの内容を確認。 |
| 品川区民まつり 品川第二地区 | no | official_current_year | official_current_year | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | 品川区公式ページで、2026年7月25日〜26日の天妙国寺境内の盆踊りを確認。既存URLの source_kind を公式扱いへ補正。 |

## Notes

- This is Master RDB only. Regenerate public JSON after apply to surface official links.
- The script does not call Notion, S3, or any external API.
