**Findings**

1. **Medium: `guard_public_events_sync.py` の pass が「公開GO」に見えやすい**
   [guard_public_events_sync.py](/Users/ryotauchida/bon-odori-collector/guard_public_events_sync.py:166) で `status == "pass"` だけを根拠に `safe_to_wholesale_sync` と `safe_to_deploy_without_review` を `True` にしています。実際の [data/public_events_sync_guard.md](/Users/ryotauchida/bon-odori-collector/data/public_events_sync_guard.md:5) では pass ですが、postprocess 後には `fixed_date_rule_basis_refresh` が 1 件残っています。これは非ブロック扱いとしては妥当でも、「deploy without review」は強すぎる表現です。
   Runbook は [docs/ph2-event-occurrence-apply-runbook.md](/Users/ryotauchida/bon-odori-collector/docs/ph2-event-occurrence-apply-runbook.md:17) で public deploy を別承認にしているので、運用上は guard pass = deploy可 ではありません。

2. **Medium: `build_master_rdb.py` は既存 master DB を無条件に作り直す**
   [master_db.py](/Users/ryotauchida/bon-odori-collector/master_db.py:403) の `init_db()` は既存 DB を `unlink()` して再作成します。今回の「現行 source snapshot からのローカル再ビルド」では許容範囲ですが、Ph2 以降に DB 内だけの apply 状態が入った後に再実行すると、その状態は消えます。
   [audit_master_rdb.py](/Users/ryotauchida/bon-odori-collector/audit_master_rdb.py:182) は source snapshot との件数・構造監査が中心なので、この喪失は `issue_count=0` では検出できません。

3. **Low: 再ビルド手順の manifest に observed candidates が残らない**
   実行順 `build_master_rdb.py` → `build_observed_promotion_candidates.py` → `build_registered_event_investigation_queue.py` → `build_historical_promotion_candidates.py` 自体は妥当です。`registered_event_investigation_queue` は [build_registered_event_investigation_queue.py](/Users/ryotauchida/bon-odori-collector/build_registered_event_investigation_queue.py:21) で observed candidates を入力にしています。
   ただし [data/bon_odori_master_manifest.json](/Users/ryotauchida/bon-odori-collector/data/bon_odori_master_manifest.json:36) の `post_build_steps` には observed step が記録されていません。現在の生成時刻は整合していましたが、manifest だけを見て再現すると stale な observed JSON を読むリスクがあります。

**Open Questions / Residual Risk**

- 件数増加は自然に見えます。Notion snapshot は venues 213 / events 222 / songs 141、Master RDB は venues 213 / event_occurrences 222 / songs 141。event_series 221 は `SHIBUYA MIYASHITA PARK BON DANCE` の 2025/2026 が同一系列にまとまるため、説明可能です。
- `audit_master_rdb.py issue_count=0` は、FK、重複、source drift、主要件数の監査としては信頼できます。ただし意味論的な監査、例えば未解決曲 179 件・observed unmatched 1774 件の妥当性判定、DB-only apply 状態の保持確認までは含みません。
- `fixed_date_rule_basis_refresh` の非ブロック扱いは概ね妥当です。[classify_public_events_diff.py](/Users/ryotauchida/bon-odori-collector/classify_public_events_diff.py:252) で同一日付・同一 date_end・固定日系 rule_type・同一スコア帯を確認しており、[tests/test_classify_public_events_diff.py](/Users/ryotauchida/bon-odori-collector/tests/test_classify_public_events_diff.py:153) に専用テストがあります。
- こちらの環境では pytest 再実行はできませんでした。`pytest` 起動時に一時ディレクトリが使えず失敗しており、テスト本体の失敗ではありません。実装担当メモの `PYTHONPATH=. pytest: 338 passed` は未再現です。

**Recommended Next Steps**

1. commit 前に `guard_public_events_sync.py` の `safe_to_deploy_without_review` 表現をやめるか、少なくとも「deploy approval とは別」と明記する。
2. `build_master_rdb.py` は既存 DB がある場合に `--force-rebuild-from-snapshot` 的な明示フラグを要求するか、DB-only 状態を持つテーブルが空でない場合に止める。
3. manifest に `build_observed_promotion_candidates.py` と `data/observed_promotion_candidates.json` を記録する。
4. commit 分割は、`master_db.py` + migration scripts + tests、設計/runbook docs、generated master/audit artifacts、public output modified、YouTube side changes、housekeeping を分けるのが安全です。
5. public sync guard pass は「wholesale deploy OK」ではなく、次のレビュー材料として扱う。公開反映は runbook 通り別承認にする。