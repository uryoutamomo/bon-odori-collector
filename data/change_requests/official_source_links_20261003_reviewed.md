# Reviewed Change Requests Promotion

- generated_by: scripts/promote_change_requests_for_review.py
- reviewed_by: おと（Codex）
- reviewed_at: 2026-10-03T05:27:40.273381+00:00
- source_request_count: 4
- approved_request_count: 4
- skipped_request_count: 0

## Change Types

- confirm_current_year_date: 4

## Guard

- `dry_run_only` was removed only from approved requests.
- `request_id` values are preserved for apply-side idempotency.
- This script does not apply to the Master RDB.
