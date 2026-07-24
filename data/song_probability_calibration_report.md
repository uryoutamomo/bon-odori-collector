# Song probability RDB calibration report (Phase 1: direct evidence only)

- generated_at: 2026-07-24T08:33:52.694724+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- backup_db: `data/backups/bon_odori_master.20260724T083352.694724+0000.sqlite.bak`
- db_committed: True
- rolled_back: False

## Summary

- targets_considered: 293
- rows_updated: 293
- rows_skipped_no_current_evidence: 0
- probability_min: 55
- probability_max: 99
- basis_distribution: {'current_observed': 293}
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}
- table_counts: {'event_investigation_tasks': 79, 'event_occurrences': 252, 'event_series': 241, 'evidence_items': 31183, 'external_record_links': 2654, 'historical_promotion_candidates': 16, 'master_meta': 0, 'notion_sync_jobs': 0, 'observed_occurrence_songs': 30772, 'observed_occurrences': 2164, 'occurrence_dates': 294, 'occurrence_evidence_links': 100, 'occurrence_song_evidence_links': 863, 'occurrence_songs': 605, 'predicted_occurrence_dates': 14, 'review_inbox_items': 0, 'schema_migrations': 1, 'song_aliases': 141, 'songs': 339, 'venue_aliases': 290, 'venues': 241, 'write_batches': 0}

## Scope

- Only fills occurrence_songs rows where probability IS NULL.
- Only uses evidence directly linked to that occurrence_song's own year (current_predictions / current_observed branches of the legacy algorithm).
- Cross-year inheritance (past_evidence/prior branches) is out of scope for this pass -- no row had inherited_from_year set at calibration time.
- Existing non-NULL probability values (legacy JSON transcriptions) are left untouched.
