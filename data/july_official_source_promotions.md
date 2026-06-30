# July official source promotions

- generated_at: 2026-06-30T14:21:40.627614+00:00
- mode: apply
- applied: True
- checked_count: 4
- updated_count: 1
- already_current_count: 3
- backup_db: data/backups/bon_odori_master.20260630T142140.627614+0000.sqlite.bak

| event | changed | before source_kind | after source_kind | source_url | reason |
| --- | --- | --- | --- | --- | --- |
| みたままつり 納涼民踊のつどい | no | official_current_year | official_current_year | https://www.yasukuni.or.jp/schedule/saiji.html#saiji03 | 靖国神社公式の祭事ページで、みたままつり 7月13日〜16日と期間中の盆踊りを確認。 |
| 佐竹ゲバゲバ盆踊り | no | official_current_year | official_current_year | https://satakeshotengai.com/satakeodori/ | 佐竹商店街公式サイトのサタケオドリ専用ページで、2026年7月18日開催と佐竹ゲバゲバ盆踊りの内容を確認。 |
| 品川区民まつり 品川第二地区 | no | official_current_year | official_current_year | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | 品川区公式ページで、2026年7月25日〜26日の天妙国寺境内の盆踊りを確認。既存URLの source_kind を公式扱いへ補正。 |
| すみだ河内音頭 小盆踊り | yes | notion_events | official_current_year | https://www.kinshicho-kawachiondo.jp/archives/1067 | すみだ錦糸町河内音頭大盆踊り公式サイトで、2026年5月16日開催と本所地域プラザ BIG SHIP 多目的ホールを確認。既存URLの source_kind を公式扱いへ補正。 |

## Notes

- This is Master RDB only. Regenerate public JSON after apply to surface official links.
- The script does not call Notion, S3, or any external API.
