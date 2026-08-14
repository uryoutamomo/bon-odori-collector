# J0-read §9 acceptance-condition coverage

This is a deliberately honest mapping: a test may cover several conditions, and
`uncovered` means the condition still needs a dedicated regression test.

| §9 | Current evidence |
|---|---|
| 1–5 | `uncovered` |
| 6–8 | `test_packet_ids_are_deterministic_for_identical_row`; `uncovered` (source/target hash mutation) |
| 9–11 | `test_packet_dry_run_writes_report_and_disables_retry_without_occurrence`; `uncovered` (max limit) |
| 12–16 | `uncovered` |
| 17–20 | `test_untrusted_actor_identity_and_timestamp_are_overwritten` |
| 21 | `test_untrusted_payload_extra_field_is_rejected` |
| 22–26 | `uncovered` |
| 27–29 | `test_apply_result_writes_ledgers_releases_claim_and_reports`; `uncovered` (hold JSON columns) |
| 30–32 | `uncovered` |
| 33–34 | `test_apply_keeps_canonical_facts_and_candidate_status_unchanged` |
| 35 | `uncovered` (561 legacy-row fixture) |
| 36–39 | `uncovered` |
| 40–43 | `test_packet_apply_requires_its_own_confirmation`; `test_result_apply_requires_its_own_confirmation`; `test_no_auto_migrate_refuses_missing_claim_ledger`; `uncovered` (checksum/same path) |
| 44 | `test_both_clis_parse_real_argv` |
| 45 | `test_packet_dry_run_writes_report_and_disables_retry_without_occurrence` |
| 46 | `test_no_auto_migrate_refuses_missing_claim_ledger` |
| 47–49 | `uncovered` |
| 50 | `test_apply_result_writes_ledgers_releases_claim_and_reports`; `test_both_clis_parse_real_argv` |
| 51 | `test_ten_day_expiry_retry_window_is_contract_valid` (packet calculation only; end-to-end defer still uncovered) |
| 52–55 | `uncovered` except `test_packet_apply_requires_its_own_confirmation` (#55) |

The initial implementation reported aggregate test counts as if they were this
matrix. That was incorrect; this map is the source of truth for follow-up work.
