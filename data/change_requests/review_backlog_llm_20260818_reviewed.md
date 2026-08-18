# Reviewed Change Requests Promotion

- generated_by: scripts/promote_change_requests_for_review.py
- reviewed_by: おと（Codex）
- reviewed_at: 2026-08-18T08:02:51.707707+00:00
- source_request_count: 394
- approved_request_count: 394
- skipped_request_count: 0

## Change Types

- merge_song_identity: 84
- record_youtube_review_decision: 247
- register_song_candidate: 8
- retract_song_identity: 55

## Guard

- `dry_run_only` was removed only from approved requests.
- `request_id` values are preserved for apply-side idempotency.
- This script does not apply to the Master RDB.
