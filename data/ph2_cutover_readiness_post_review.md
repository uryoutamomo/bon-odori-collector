# Ph2 cutover readiness

- generated_at: 2026-06-22T03:38:53.213732+00:00
- scope: read_only_local_review_material

## Master DB

- event_series: 221
- event_occurrences: 222
- occurrence_dates: 141
- predicted_occurrence_dates: 12
- historical_promotion_candidates: 15
- event_investigation_tasks: 88
- occurrences_by_year: {2023: 1, 2025: 99, 2026: 122}
- occurrences_by_date_status: {'ended': 122, 'confirmed': 16, 'unknown': 81, 'predicted': 3}
- missing_core_fields: {'date_start': 81, 'venue_id': 12, 'source_url': 6}
- predicted_dates_by_application_status: {'superseded_by_curated': 1, 'candidate_for_2026_occurrence': 10, 'matches_curated': 1}
- dry_run_sync_jobs_by_status: {'pending': 10}

### Duplicate Series Name Examples

- 郡上おどりin青山: 2

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

- changed_file_count: 23
- groups: {'master_rdb_generated_artifacts': 3, 'other': 20}

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
