# Official notice report apply result

- generated_at: 2026-08-03T15:44:41.435156+00:00
- mode: apply
- resolved: True
- events_applied: 17
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260803T154441.435156+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_5d95e7c12e909ab4`

## Applied events

- register_new occ_ad6ed05fa96c3735 (songs: 0; series_id: `series_627b5db2f9ae3930`, series_created: True, venue_status: created)
- register_new occ_f6616b661a481009 (songs: 0; series_id: `series_96807098828ca94f`, series_created: True, venue_status: created)
- register_new occ_9504af8dd208ca10 (songs: 0; series_id: `series_e7349663494a3ce4`, series_created: True, venue_status: created)
- register_new occ_5c45e92cefe80416 (songs: 0; series_id: `series_4306c6c45dd35786`, series_created: True, venue_status: created)
- register_new occ_704e02ef8a303789 (songs: 0; series_id: `series_633979806e8ef526`, series_created: True, venue_status: created)
- register_new occ_d5fe44f35a4c6208 (songs: 0; series_id: `series_c37c2b6ced870ac2`, series_created: True, venue_status: created)
- register_new occ_30f0498f563b2112 (songs: 0; series_id: `series_00513980bee2bc85`, series_created: True, venue_status: created)
- register_new occ_210070a96556cbd1 (songs: 0; series_id: `series_214d03fbab388114`, series_created: True, venue_status: created)
- register_new occ_c1d14ab9991f5c74 (songs: 0; series_id: `series_ed7cf525f8169c30`, series_created: True, venue_status: created)
- register_new occ_9451ac100f1d2458 (songs: 0; series_id: `series_c5a4942c2d5d653e`, series_created: True, venue_status: created)
- register_new occ_f8047d46e100b5a1 (songs: 0; series_id: `series_7d6b118f0d39322c`, series_created: True, venue_status: created)
- register_new occ_fa48ecbc1a691232 (songs: 0; series_id: `series_073256bee502c6fc`, series_created: True, venue_status: created)
- register_new occ_d3250992e775db8a (songs: 0; series_id: `series_ada37b85685af308`, series_created: True, venue_status: created)
- register_new occ_3513df648eddf5bb (songs: 0; series_id: `series_185e3f341922b291`, series_created: True, venue_status: created)
- register_new occ_39a8a80f2b3c2449 (songs: 0; series_id: `series_d39b946bd732794b`, series_created: True, venue_status: created)
- register_new occ_950d73869e1a34de (songs: 0; series_id: `series_f5a24882376cf072`, series_created: True, venue_status: created)
- register_new occ_96854e6c02eba84d (songs: 0; series_id: `series_5c3f1ea3e4d5172d`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
