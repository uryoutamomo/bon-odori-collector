# Ph2 cutover readiness

- generated_at: 2026-06-22T10:30:10.326962+00:00
- scope: read_only_local_review_material

## Master DB

- event_series: 221
- event_occurrences: 222
- occurrence_dates: 170
- predicted_occurrence_dates: 12
- historical_promotion_candidates: 15
- event_investigation_tasks: 79
- occurrences_by_year: {2023: 1, 2025: 99, 2026: 122}
- occurrences_by_date_status: {'ended': 122, 'confirmed': 20, 'unknown': 77, 'predicted': 3}
- missing_core_fields: {'date_start': 77, 'venue_id': 7, 'source_url': 4}
- predicted_dates_by_application_status: {'superseded_by_curated': 2, 'candidate_for_2026_occurrence': 9, 'matches_curated': 1}
- dry_run_sync_jobs_by_status: {'pending': 9, 'superseded_by_curated': 1}

### Duplicate Series Name Examples


### Occurrence Split Risk Examples

- 品川区民まつり 大崎第一地区: venues=["第四日野小学校", "第一日野小学校"] priority=P1 score=7
- 押上二町目町会 飛木稲荷神社神幸大祭 奉納おどり: venues=["飛木稲荷神社", "押上二丁目町会会館前 路上"] priority=P1 score=6

## Collector vs Site Public Events

- collector_event_count: 183
- site_event_count: 183
- collector_only_count: 0
- site_only_count: 0
- common_rows_with_diff: 0
- high_risk_diff_counts: {}

### Top Field Diffs


### High-Risk Diff Examples

## Worktree Triage

- changed_file_count: 137
- groups: {'other': 84, 'review_commit_candidate_scripts': 3, 'master_rdb_generated_artifacts': 24, 'new_review_reports': 26}

### Suggested Review Buckets

- review_commit_candidate_scripts/docs: keep together as migration implementation review.
- master_rdb_generated_artifacts/review_queue_reports/new_review_reports: keep as generated review evidence, or regenerate during review.
- public_output_modified: do not deploy wholesale; only release scoped Ph1 public song outputs.
- youtube_song_master_side_changes: review separately from the master RDB cutover.

## Recommended Next Actions

- Keep data/song_occurrences.json and prediction snapshots frozen until Ph2/Ph3 explicitly reopens the legacy path.
- Do not copy collector data/public/events_public.json wholesale to bon-odori-site until high-risk field diffs are classified.
- Use predicted_occurrence_dates and event_investigation_tasks as review queues, not as automatic public updates.
- Proceed with Ph2 dry-run against event_series/event_occurrences before any large Notion or public JSON write.
