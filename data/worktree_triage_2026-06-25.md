# Worktree triage 2026-06-25

- generated_at: 2026-06-25T22:49:06+0900
- generated_by: おと（Codex）
- scope: collector worktree after Master RDB public export, Notion drift freeze review, and YouTube daily snapshot commits
- action_taken: committed safe groups only; freeze/noisy/local runtime files left uncommitted

## Commits Made

- `8d0f683` Regenerate public event export from Master RDB
- `f908b5e` Record reviewed Notion drift freeze state
- `8ba3533` Record YouTube daily backfill snapshot

## Verified

- public export focused tests: `33 passed`
- YouTube/year-occurrence focused tests: `25 passed`
- relevant `py_compile`: passed
- public sync guard: pass, not a deploy approval
- RDB -> Notion dry-run: selected 0, ready 0, applied 0

## Remaining Holds

Do not commit as ordinary generated data:

- `data/song_occurrences.json`
- `data/song_prediction_snapshots.json`
- `data/public/event_song_occurrences_public.json`

Reason: `legacy_song_occurrence_generation` is frozen. These files have large churn and should only move under an explicit song-generation/source-of-truth decision.

Hold as noisy review artifacts:

- `data/public_historical_reference_dry_run.json`
- `data/public_season_hint_dry_run.json`

Reason: these are large dry-run/postprocessor reports regenerated from current public data. They are useful locally, but not needed for the committed public JSON snapshot.

Hold until source checksum state is clean:

- `data/master_rdb_audit.json`
- `data/master_rdb_audit.md`

Reason: the regenerated audit currently sees the uncommitted song occurrence files and reports `song_occurrences` source drift. Committing the audit alone would record a checksum for a held local source state.

Hold as timestamp-only snapshot churn:

- `data/notion_rdb_summary.json`

Reason: only `generated_at` changed. No useful data delta.

Local runtime state; do not commit:

- `data/pending_mail.json`

Reason: mail/reminder runtime payload from the YouTube daily run.

## Current Recommendation

The repository has the useful safe updates pushed. Leave the remaining files uncommitted until either:

1. the frozen song occurrence generation path is intentionally reopened, or
2. the local runtime/noisy generated outputs are discarded after operator confirmation.
