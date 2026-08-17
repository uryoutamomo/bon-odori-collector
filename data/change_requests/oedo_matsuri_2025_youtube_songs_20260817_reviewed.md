# Reviewed Change Requests Promotion

- generated_by: scripts/promote_change_requests_for_review.py
- reviewed_by: おと（Codex）
- reviewed_at: 2026-08-17T14:30:29.261640+00:00
- source_request_count: 1
- approved_request_count: 1
- skipped_request_count: 0

## Change Types

- add_song_evidence: 1

## Guard

- `dry_run_only` was removed only from approved requests.
- `request_id` values are preserved for apply-side idempotency.
- This script does not apply to the Master RDB.
