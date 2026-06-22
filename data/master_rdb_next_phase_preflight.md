# Master RDB next phase preflight

- generated_at: 2026-06-22T15:00:00Z
- generated_by: おと（Codex）
- status: ready_for_operator_decision
- current_local_phase: complete_for_local_rdb_phase

## Safe Without Approval

- Regenerate dry-run reports
- Refresh read-only guards
- Review queues and source evidence
- Run tests, audits, and large-file guard

## Requires Explicit Approval

- Notion production sync
- public JSON wholesale sync
- site deploy
- automatic promotion of predicted 2026 dates
- moving the tracked SQLite file out of Git

## Current Blockers

- predicted occurrence research queue: 8 items, review-only until current-year source confirmation
- keep_investigation_queue: 3 items
- keep_investigation_queue events: 増上寺 地蔵尊盆踊り大会 / 旗岡八幡神社例大祭 / 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！
- historical promotion candidate review: 15 candidates, 10 already have historical references, 5 remain review-only

## Notion Preflight

- event_occurrence dry-run: selected 0 / ready 0 / skipped 0
- predicted_date dry-run: selected 8 / ready 0 / skipped 8
- status: dry-run reports refreshed, not ready for apply
- refreshed reports:
  - `data/ph2_master_to_notion_sync_dry_run.json`
  - `data/ph2_master_to_notion_sync_tmp_apply_db_dry_run.json`
- source snapshot drift: `data/notion_snapshot.sqlite` was refreshed after the current master DB build, so `audit_master_rdb.py` reports one medium `source_snapshot_drift` issue.
- rebuild safety check: plain `python3 build_master_rdb.py` refuses to overwrite the existing master DB; this guard is working.
- do not force rebuild from snapshot at this stage: a temp rebuild from current snapshots would drop DB-only review state (`notion_sync_jobs`, `predicted_occurrence_dates`, `event_investigation_tasks`, `historical_promotion_candidates`).
- next local-only step before any apply: design or run a state-preserving source refresh, then rerun audit and dry-run reports.

## Public Preflight

- collector_event_count: 183
- site_event_count: 183
- collector_only_count: 0
- site_only_count: 0
- common_rows_with_diff: 0
- high_risk_diff_counts: {}
- status: guard pass, but not deploy approval

## Verification Before Any Apply

```bash
python3 build_notion_rdb.py
python3 sync_master_to_notion.py --target-table event_occurrences --out-json data/ph2_master_to_notion_sync_dry_run.json --out-md data/ph2_master_to_notion_sync_dry_run.md
python3 guard_public_events_sync.py
PYTHONPATH=. pytest -q
python3 audit_master_rdb.py
python3 guard_git_large_files.py
```
