# Oto2 review after Master RDB rebuild

作成: 2026-06-22 / おと（Codex）

## 実行・確認したこと

- 別 Codex を review-only で起動し、Master RDB 再ビルド後の生成物・guard・監査を横からレビューした。
- おと2側でも `python3 -m pytest -q` を再実行し、`338 passed` を確認した。
- deploy / push / 本番 Notion 同期 / 公開 wholesale deploy は実行していない。
- ことには、MCP 連絡ログで現状・レビュー依頼・残リスクを送信済み。

## 現時点の判断

- Master RDB の件数と source snapshot の対応は大きく崩れていない。
- `audit_master_rdb.py` は `issue_count=0` で、以前の `source_snapshot_drift` / `source_count_drift` は解消している。
- public events は collector/site とも 182 件で、raw common diff は 0。公開JSONから `fixed_date_rule` の漏れも検出されなかった。
- `fixed_date_rule_basis_refresh` 1件は、表示日・終了日・固定日ルール・スコア帯が同等なので非ブロック扱いは概ね妥当。
- ただし guard の pass は「公開反映してよい」という意味にしてはいけない。公開反映は別承認が必要。

## 指摘

### Medium: public sync guard の文言が強すぎる

`guard_public_events_sync.py` は `status == "pass"` のとき `safe_to_wholesale_sync` と `safe_to_deploy_without_review` を true にする。

実際には postprocess 後に `fixed_date_rule_basis_refresh` が 1 件残っており、非ブロックではあるがレビュー材料ではある。`safe_to_deploy_without_review` は、内田さんや後続作業者に「公開GO」と誤読されやすい。

対応案:
- `safe_to_deploy_without_review` を削除または `requires_deploy_approval` のような別フラグへ変更。
- markdownにも「guard pass は deploy 承認ではない」と明記する。

### Medium: Master RDB の再ビルドが既存 DB を無条件に作り直す

`master_db.py` の `init_db()` は既存 `data/bon_odori_master.sqlite` を削除して再作成する。

今回のように「現行 snapshot からローカル再ビルドする」用途では許容できるが、Ph2以降に DB 内だけの apply 状態が入った後に実行すると、その状態を消す可能性がある。`audit_master_rdb.py issue_count=0` ではこの種類の喪失は検出できない。

対応案:
- 既存 DB がある場合は `--force-rebuild-from-snapshot` のような明示フラグを要求する。
- または DB-only 状態を持つテーブルが空でない場合に停止する。

### Low: manifest だけでは post-build の再現手順が足りない

今回の実行順は以下で妥当:

1. `build_master_rdb.py`
2. `build_observed_promotion_candidates.py`
3. `build_registered_event_investigation_queue.py`
4. `build_historical_promotion_candidates.py`

ただし `data/bon_odori_master_manifest.json` の `post_build_steps` には observed candidates の step が記録されていない。`registered_event_investigation_queue` は observed candidates を入力にするため、manifest だけ見て再実行すると stale な observed JSON を使うリスクがある。

対応案:
- manifest に `build_observed_promotion_candidates.py` と `data/observed_promotion_candidates.json` を記録する。

## 補足

- Notion snapshot と Master RDB の主要件数は整合している: venues 213、events/event_occurrences 222、songs 141。
- event_series が 221 なのは、`SHIBUYA MIYASHITA PARK BON DANCE` の 2025/2026 が同一 series にまとまっているため説明可能。
- 未解決キューは残っている: unresolved occurrence songs 179、observed unmatched occurrences 1774、observed unmatched songs 20541。これは移行監査の失敗ではなく、今後のレビュー・照合対象。

## 次に進めるなら

1. commit 前に上記3点を軽く直す。
2. 修正後に `python3 -m pytest -q`、`python3 audit_master_rdb.py`、`python3 guard_public_events_sync.py` を再実行する。
3. 生成物を commit 分割する。少なくとも migration scripts/tests、docs/runbook、generated audit artifacts、public output、YouTube side changes は分ける。
4. ことが復旧したら、このメモと `data/oto_impl_handoff.md`、`data/oto2_reviewer_codex_result.md` を見てもらう。

