# Master RDB audit

- generated_at: 2026-07-27T06:06:28.740781+00:00
- database: data/bon_odori_master.sqlite
- issue_count: 1
- issues_by_severity: {'medium': 1}

## Table counts

- event_investigation_tasks: 79
- event_occurrences: 254
- event_series: 242
- event_series_aliases: 21
- evidence_items: 31303
- external_record_links: 2654
- historical_promotion_candidates: 16
- master_meta: 0
- notion_sync_jobs: 0
- observed_occurrence_songs: 30883
- observed_occurrences: 2164
- occurrence_dates: 299
- occurrence_evidence_links: 103
- occurrence_song_evidence_links: 1008
- occurrence_songs: 820
- predicted_occurrence_dates: 14
- review_inbox_items: 386
- schema_migrations: 4
- song_aliases: 141
- songs: 394
- venue_aliases: 301
- venues: 241
- write_batches: 0

## Check counts

- duplicate_series_year_sequence: 0
- duplicate_occurrence_song_role: 0
- empty_venue_name: 0
- empty_song_title: 0
- empty_series_name: 0
- non_curated_venues: 0
- non_curated_series: 0
- non_curated_occurrences: 0
- date_cache_mismatch: 0
- historical_reference_dates: 113
- unresolved_occurrence_songs: 210
- observed_unmatched_occurrences: 2050
- observed_discard_candidate_occurrences: 126
- observed_out_of_scope_occurrences: 61
- observed_unmatched_songs: 21998
- historical_promotion_candidates: 16
- historical_auto_promote_eligible: 13
- predicted_occurrence_dates: 14
- predicted_occurrence_dates_date_based: 3
- predicted_occurrence_dates_weekday_based: 11
- predicted_occurrence_dates_year_mismatch: 0
- predicted_occurrence_dates_detached_series_only: 6
- predicted_occurrence_dates_superseded_by_curated: 5
- predicted_occurrence_dates_matches_curated: 2
- predicted_occurrence_date_sync_jobs: 0
- review_inbox_schema_version: 2
- review_inbox_missing_v2_columns: 0

## Issues

- medium source_snapshot_drift: Current source snapshot differs from the master DB build manifest. {'manifest_source_checksums': {'notion_db': '20e460fa51a838cfc4e8c3e1a34e51d60707870eb39534d98d8673d1e1d67002', 'song_occurrences': '2f129469c58dce45b8671dc964b0e62b882c999a06f181172a237ac04bf6e609'}, 'current_source_checksums': {'notion_db': 'd7f45902c9c235298c4cce58531cf79c46f353dfda1dc66e78b15c11abbe2622', 'song_occurrences': '2f129469c58dce45b8671dc964b0e62b882c999a06f181172a237ac04bf6e609'}, 'source_drift': {'notion_db': True, 'song_occurrences': False}, 'resolution': 'Refresh the master DB from current source snapshots with a state-preserving process during Ph2 cutover; do not force-rebuild after DB-only review state exists.'}
