# Official notice report apply result

- generated_at: 2026-08-08T08:25:05.766756+00:00
- mode: apply
- resolved: True
- events_applied: 48
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260808T082505.766756+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_6c548bc34b8aeb75`

## Applied events

- confirm_existing occ_0c9c275ac96c14b8 (songs: 0)
- confirm_existing occ_0ee14ffbf15fd0cf (songs: 0)
- confirm_existing occ_c269edeedf7a5b71 (songs: 0)
- confirm_existing occ_251ebd5fe04d4d38 (songs: 0)
- confirm_existing occ_9a6845c9eef189a2 (songs: 0)
- confirm_existing occ_fd1c503d3f6538d5 (songs: 0)
- confirm_existing occ_c144b96d770e3b9e (songs: 0)
- confirm_existing occ_fbbf1f3dcb7ae7c3 (songs: 0)
- confirm_existing occ_67944b1715f8aaa4 (songs: 0)
- confirm_existing occ_4c6f06222bd906ac (songs: 0)
- confirm_existing occ_4fcc747c2d490ae4 (songs: 0)
- confirm_existing occ_144344004e460a1a (songs: 0)
- confirm_existing occ_d4f2f14192a4ef64 (songs: 0)
- confirm_existing occ_5df32308eae3f789 (songs: 0)
- confirm_existing occ_e2b9ec2298ec4f32 (songs: 0)
- confirm_existing occ_64e9d25c0c48cc6b (songs: 0)
- confirm_existing occ_31f1726dde1f04b9 (songs: 0)
- confirm_existing occ_4ed149af2fc84735 (songs: 0)
- confirm_existing occ_cf0544b3561983b8 (songs: 0)
- confirm_existing occ_22f885022cdf1584 (songs: 0)
- confirm_existing occ_472f2827e41b676b (songs: 0)
- confirm_existing occ_ef53e510c8842afb (songs: 0)
- confirm_existing occ_b223cacd3b0c84eb (songs: 0)
- confirm_existing occ_12e9728c0a384d1b (songs: 0)
- confirm_existing occ_5c0b8546b2496353 (songs: 0)
- confirm_existing occ_eaaff144ec744dd6 (songs: 0)
- confirm_existing occ_704e02ef8a303789 (songs: 0)
- confirm_existing occ_c1d14ab9991f5c74 (songs: 0)
- confirm_existing occ_d3250992e775db8a (songs: 0)
- confirm_existing occ_96854e6c02eba84d (songs: 0)
- confirm_existing occ_950d73869e1a34de (songs: 0)
- confirm_existing occ_9451ac100f1d2458 (songs: 0)
- confirm_existing occ_210070a96556cbd1 (songs: 0)
- confirm_existing occ_3513df648eddf5bb (songs: 0)
- confirm_existing occ_c0077e9258ce2e98 (songs: 0)
- confirm_existing occ_9504af8dd208ca10 (songs: 0)
- confirm_existing occ_39a8a80f2b3c2449 (songs: 0)
- confirm_existing occ_8d8a4036f11c5874 (songs: 0)
- confirm_existing occ_5c45e92cefe80416 (songs: 0)
- confirm_existing occ_30f0498f563b2112 (songs: 0)
- confirm_existing occ_d5fe44f35a4c6208 (songs: 0)
- confirm_existing occ_f8047d46e100b5a1 (songs: 0)
- confirm_existing occ_fc74cc7f0868ba17 (songs: 0)
- confirm_existing occ_fa48ecbc1a691232 (songs: 0)
- confirm_existing occ_f6616b661a481009 (songs: 0)
- confirm_existing occ_ad6ed05fa96c3735 (songs: 0)
- confirm_existing occ_1df0a276422a54b5 (songs: 0)
- confirm_existing occ_4708707c25bc756e (songs: 0)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
