# LLMレビュー判断の正本反映 dry-run

生成日時: 2026-08-18T17:45:00+09:00

この計画は読み取り専用です。SQLiteはSHA-256を照合してからread-onlyで開き、DB・公開データ・reader設定を変更しません。

## 結論

- 対象判断: 505件
- そのまま本番書き込み可能: 0件
- 公開サイト側の別同期計画: 12件
- 2026年日付へ昇格可能: 0件

専用のrelink・merge・retraction・候補登録処理、YouTube identity packet、公開サイト側同期が未作成です。正本反映には、各処理の実装・コピーDBでの検証・対象を特定した明示GOが別途必要です。

## DB照合結果

- 判断時点DBとのSHA一致: `True`
- 曲名判断: 147件 / 該当occurrence_songs 72行
- RDBに統合先がない判断: 16件
- 同一開催・役割内でmergeが必要な衝突行: 2行
- YouTube判断: 247件

| 分類 | dry-run action | 件数 |
|---|---|---:|
| 曲名判断 | `already_matched_current_rdb` | 5 |
| 曲名判断 | `blocked_target_song_missing_from_rdb` | 16 |
| 曲名判断 | `requires_candidate_registration_from_public_source` | 8 |
| 曲名判断 | `requires_merge_materializer` | 2 |
| 曲名判断 | `requires_relink_materializer` | 7 |
| 曲名判断 | `requires_retraction_materializer` | 11 |
| 曲名判断 | `source_public_only_no_rdb_row` | 98 |
| YouTube判断 | `already_present_or_partially_materialized` | 4 |
| YouTube判断 | `no_canonical_write` | 32 |
| YouTube判断 | `no_write_retraction_review_required` | 4 |
| YouTube判断 | `requires_identity_packet_before_materialize` | 207 |

## 書き込み禁止として維持する判断

- 過去実績維持: 60件（現在年の事実へ転用しない）
- 2026年日付の根拠不足: 38件
- X由来・公式確認待ち: 1件
- YouTube不採用: 36件

## 次の安全な実装単位

1. 曲名relink/merge/retractionをコピーDBだけに適用するmaterializerを作る。
2. 新規曲候補を根拠URL付きで登録するmaterializerを作る。
3. 採用YouTubeをイベント・曲へ結ぶidentity packetを作り、曖昧一致を人手確認へ戻す。
4. 公開同期12件は `bon-odori-site` 側で別計画・別承認にする。

イベント日付について、2025年以前、YouTube、年次未指定の恒例案内を2026年日付へ転用しません。
