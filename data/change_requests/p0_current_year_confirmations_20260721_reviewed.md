# Reviewed Change Requests Promotion

- generated_by: scripts/promote_change_requests_for_review.py
- reviewed_by: おと（Codex）
- reviewed_at: 2026-07-21T02:54:32.315782+00:00
- source_request_count: 3
- approved_request_count: 3
- skipped_request_count: 0

## Change Types

- confirm_current_year_date: 2
- create_current_year_occurrence: 1

## Guard

- `dry_run_only` was removed only from approved requests.
- `request_id` values are preserved for apply-side idempotency.
- This script does not apply to the Master RDB.
