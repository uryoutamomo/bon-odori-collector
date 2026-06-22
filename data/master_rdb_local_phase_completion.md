# Master RDB local phase completion

- generated_at: 2026-06-22T14:33:41Z
- generated_by: おと（Codex）
- head_commit: `569eef1`
- status: complete_for_local_rdb_phase

## Scope Closed

- RDB audit is clean: issue_count 0
- Local review queues are regenerated from the current RDB state
- Predicted occurrence candidates remain review queues, not Notion/public writes
- Historical reference candidates already recorded are no longer shown as ready-to-insert
- GitHub large-file guard is installed and wired into the collect workflow
- Ph2 readiness reports clean worktree, public_common_diffs 0, high_risk_fields {}

## Verification

- `PYTHONPATH=. pytest -q`: 351 passed
- `python3 audit_master_rdb.py`: issues 0
- `python3 guard_git_large_files.py`: warns on `data/bon_odori_master.sqlite` at 50.76 MiB; blocks at 95 MiB
- `data/ph2_cutover_readiness.md`: worktree_files 0

## Current Counts

- event_series: 221
- event_occurrences: 222
- occurrence_dates: 171
- historical_reference_dates: 25
- predicted_occurrence_dates: 12
- event_investigation_tasks: 79

## Remaining Queues

- pre-cutover P0: 11 rows
- historical references already recorded: 8
- keep_investigation_queue: 3
- pre-cutover human_review_required_count: 0
- predicted occurrence research queue: 8 items, P0 4 / P1 3 / P2 1
- historical promotion candidate review: 10 already recorded, 5 still review-only

## Explicitly Not Done

- Notion production sync
- public JSON wholesale deploy
- automatic promotion of predicted 2026 dates without current-year confirmation
- migration of the tracked SQLite file out of Git

## Next Phase

- Ask for explicit approval before any Notion production sync or public deploy.
- Keep 増上寺, 旗岡八幡神社, and 盆☆Dance in investigation queue until current-year source appears.
- Recheck the 8 predicted occurrence candidates periodically and promote only with current-year evidence.
- Plan a separate storage strategy for `data/bon_odori_master.sqlite` before it approaches 95 MiB.
