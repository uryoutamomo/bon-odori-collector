# Song probability RDB calibration report

- generated_at: 2026-08-17T14:30:49.394821+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- backup_db: `data/backups/bon_odori_master.20260817T143049.394821+0000.sqlite.bak`
- db_committed: True
- rolled_back: False

## Summary

- targets_considered: 13
- rows_updated: 13
- rows_skipped_no_current_evidence: 0
- probability_min: 51
- probability_max: 51
- basis_distribution: {'past_evidence': 13}
- issues_by_severity: {}
- audit_issues_by_severity: {}
- table_counts: {'canonical_decision_ledger': 132, 'event_investigation_tasks': 79, 'event_occurrences': 435, 'event_series': 417, 'event_series_aliases': 25, 'evidence_items': 31428, 'external_record_links': 2654, 'historical_promotion_candidates': 16, 'local_judgment_schema_migrations': 4, 'master_meta': 0, 'notion_sync_jobs': 0, 'observed_occurrence_songs': 30883, 'observed_occurrences': 2164, 'occurrence_dates': 488, 'occurrence_evidence_links': 418, 'occurrence_song_evidence_links': 1025, 'occurrence_songs': 837, 'predicted_occurrence_dates': 14, 'review_claim_ledger': 0, 'review_hold_ledger': 48, 'review_inbox_items': 831, 'review_queue_state_ledger': 132, 'schema_migrations': 4, 'song_aliases': 142, 'songs': 402, 'venue_aliases': 475, 'venues': 411, 'write_batches': 0, 'x_occurrence_resolution_decisions': 1, 'x_song_materializations': 1, 'x_song_resolution_decisions': 1, 'x_song_retractions': 0}

## Scope

- Only fills occurrence_songs rows where probability IS NULL.
- Direct evidence uses the current_predictions/current_observed branches.
- Rows carrying inherited_from_year use past-evidence decay; this does not create new inherited rows.
- Existing non-NULL probability values (legacy JSON transcriptions) are left untouched.
