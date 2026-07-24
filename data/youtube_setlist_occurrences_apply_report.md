# YouTube setlist occurrences RDB apply report

- generated_at: 2026-07-24T08:33:44.890179+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- backup_db: `data/backups/bon_odori_master.20260724T083344.890179+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- match_score_threshold: 0.7

## Summary

- occurrences_processed: 308
- occurrences_matched: 32
- occurrences_unmatched: 276
- song_relations_written: 2667
- evidence_items_written: 2667
- song_titles_rejected: 12
- candidate_songs_registered: 181
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}
- table_counts: {'event_investigation_tasks': 79, 'event_occurrences': 252, 'event_series': 241, 'evidence_items': 31183, 'external_record_links': 2654, 'historical_promotion_candidates': 16, 'master_meta': 0, 'notion_sync_jobs': 0, 'observed_occurrence_songs': 30772, 'observed_occurrences': 2164, 'occurrence_dates': 294, 'occurrence_evidence_links': 100, 'occurrence_song_evidence_links': 863, 'occurrence_songs': 605, 'predicted_occurrence_dates': 14, 'review_inbox_items': 0, 'schema_migrations': 1, 'song_aliases': 141, 'songs': 339, 'venue_aliases': 290, 'venues': 241, 'write_batches': 0}

## Scope

- probability: intentionally left NULL (RDB-native computation is a separate follow-up)
- Notion write-back: skipped
- public JSON write: skipped (not wired into export_public_events.py yet)
