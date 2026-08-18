# Reviewed Change Requests Promotion

- generated_by: scripts/promote_change_requests_for_review.py
- reviewed_by: おと（Codex）
- reviewed_at: 2026-08-18T12:52:16.316428+00:00
- source_request_count: 4
- approved_request_count: 4
- skipped_request_count: 0

## Change Types

- add_song_evidence: 4

## Guard

- `dry_run_only` was removed only from approved requests.
- `request_id` values are preserved for apply-side idempotency.
- This script does not apply to the Master RDB.
