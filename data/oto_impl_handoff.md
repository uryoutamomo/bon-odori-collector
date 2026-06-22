# Oto implementation handoff

作成: 2026-06-22 / おと（Codex）

## 実行コマンド

- `git status --short`
- `python3 build_master_rdb.py`
- `python3 build_observed_promotion_candidates.py`
- `python3 build_registered_event_investigation_queue.py`
- `python3 build_historical_promotion_candidates.py`
- `python3 audit_master_rdb.py`
- `python3 build_ph2_cutover_readiness.py`
- `python3 guard_public_events_sync.py`
- `python3 build_ph2_review_packet.py`
- `pytest`
- `PYTHONPATH=. pytest`
- `git status --short`

## 結果

- deploy / push / Notion同期 / 公開JSONのwholesale deploy は未実行。
- Master RDB を現行 `data/notion_snapshot.sqlite` と `data/song_occurrences.json` からローカル再ビルドした。
- post-build として observed candidates、registered investigation queue、historical promotion candidates を再生成した。
- `audit_master_rdb.py`: `issues=0`。以前の `source_snapshot_drift` / `source_count_drift` は解消。
- 主な件数: venues 213、event_occurrences 222、event_series 221、occurrence_dates 140、event_investigation_tasks 88、historical_promotion_candidates 15、predicted_occurrence_dates 12、notion_sync_jobs 10。
- `build_ph2_cutover_readiness.py`: collector/site events は 182 件同士、common diffs 0、high risk diffs なし。
- `guard_public_events_sync.py`: pass、failures なし。
- `PYTHONPATH=. pytest`: 338 passed。

## 注意点・残リスク

- 素の `pytest` は import path の問題で collection error。repo root を import path に入れる必要があり、`PYTHONPATH=. pytest` では全件通過。
- 再ビルドは `data/bon_odori_master.sqlite` を作り直すため、DB内にだけ存在した手動 apply 状態は現行ソース snapshot に含まれていなければ保持されない。今回の監査目的では現行ソース再ビルドを優先した。
- worktree には作業前から多数の未コミット差分がある。今回それらを戻す操作はしていない。

## おと2レビュー対象

- `data/master_rdb_audit.md` で drift issue が消えていること。
- `data/ph2_cutover_readiness.md` の Master DB 件数と public diff が期待どおりか。
- `data/ph2_review_packet.md` の review buckets と venue review rows が現行レビュー方針に合うか。
- `data/public_events_sync_guard.md` の pass 判定を、公開反映判断とは切り離して扱えているか。
