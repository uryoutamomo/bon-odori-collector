# J0-read §9 受け入れ条件のカバー状況

正本仕様は `docs/local-judgment-j0-read-v1.md`（v1.4）。この表がテストの現況の正本です。

**1つのテストが複数の条件を守るのは構いませんが、「テストが通った」ことは条件を満たした証拠になりません。**
条件を守る回帰テストがまだ無いものは `未カバー` と正直に書くこと。**2026-08-14 時点で未カバーはありません（55/55）。**

| §9 | 守っているテスト |
|---|---|
| 1, 2 | `test_closed_or_held_candidates_are_not_packetized` |
| 3 | `test_superseded_candidate_is_not_packetized` |
| 4 | `test_expired_candidate_is_not_packetized` |
| 5 | `test_candidate_without_queue_row_is_eligible` |
| 6 | `test_packet_ids_are_deterministic_for_identical_row` |
| 7 | `test_packet_id_changes_when_the_proposal_changes` |
| 8 | `test_packet_id_survives_a_changed_candidate_set`（**仕様 v1.4 で前提を訂正**。`packet_sha256` は `targets` を含まないので、候補集合の違いは台帳から辿れない。追えるのは `data/judgment_packets/` の packet ファイルだけ） |
| 9 | `test_packet_dry_run_writes_report_and_disables_retry_without_occurrence` |
| 10 | `test_allowed_actions_follow_registry` |
| 11, 47, 48 | `test_max_packets_limits_count_and_leaves_the_rest_unclaimed` |
| 12 | `test_forged_packet_id_in_the_packet_file_is_rejected` |
| 13 | `test_result_with_a_different_source_hash_is_rejected` |
| 14 | `test_candidate_revised_while_judging_is_rejected` |
| 15 | `test_action_outside_allowed_actions_is_rejected` |
| 16 | `test_result_without_its_packet_file_stops_everything` |
| 17〜20 | `test_untrusted_actor_identity_and_timestamp_are_overwritten` |
| 21 | `test_untrusted_payload_extra_field_is_rejected` |
| 22, 28, 29 | `test_hold_for_user_writes_three_ledgers_with_serialized_json` |
| 23 | `test_declared_hold_mode_conflicting_with_reason_code_is_rejected` |
| 24 | `test_retry_candidate_outside_the_machine_list_is_rejected` |
| 25 | `test_next_eligible_at_comes_from_the_machine_candidate` |
| 26 | `test_unknown_reason_code_is_rejected` |
| 27 | `test_accept_closes_the_queue_state` |
| 30 | `test_ledger_write_rolls_back_completely_on_failure` |
| 31 | `test_reapplying_the_same_result_is_a_noop` |
| 32 | `test_same_decision_id_with_different_content_stops` |
| 33, 34 | `test_apply_keeps_canonical_facts_and_candidate_status_unchanged` |
| 35 | `test_legacy_pending_rows_are_untouched` |
| 36 | `test_candidate_claimed_by_another_actor_is_skipped` |
| 37 | `test_expired_claim_is_overwritten_without_deleting_history` |
| 38 | `test_apply_result_writes_ledgers_releases_claim_and_reports`（claim が0件になることを確認） |
| 39 | `test_force_claim_takes_over_and_is_recorded` |
| 40 | `test_packet_apply_requires_its_own_confirmation` ほか（dry-run が本番を書き換えない） |
| 41 | `test_packet_apply_requires_its_own_confirmation` / `test_result_apply_requires_its_own_confirmation` |
| 42, 46 | `test_no_auto_migrate_refuses_missing_claim_ledger` |
| 43 | `test_dry_run_target_must_differ_from_the_production_path` |
| 44 | `test_both_clis_parse_real_argv` |
| 45 | `test_packet_dry_run_writes_report_and_disables_retry_without_occurrence` |
| 49 | `test_report_records_migrations_and_claim_scope` |
| 50 | `test_apply_result_writes_ledgers_releases_claim_and_reports` / `test_both_clis_parse_real_argv` |
| 51 | `test_ten_day_expiry_retry_window_is_contract_valid`（窓の計算）＋ `test_defer_for_retry_passes_end_to_end_for_a_candidate_expiring_soon`（取り込みまでの通し） |
| 52 | `test_candidate_without_expiry_still_builds_a_retry_window` |
| 53 | `test_candidate_without_evidence_cannot_defer` |
| 54 | `test_implementation_errors_are_not_swallowed_as_invalid_results` |
| 55 | `test_packet_apply_requires_its_own_confirmation` |

## 変異チェックの実測（2026-08-14、こと）

「修正を外すと落ちるか」を実際に確かめた分です。**`__pycache__` を毎回消してから測っています。**

| 外した守り | 落ちたテスト |
|---|---|
| `queue_state` の除外条件 | `test_closed_or_held_candidates_are_not_packetized` |
| superseded の除外 | `test_superseded_candidate_is_not_packetized` |
| 期限切れの除外 | `test_expired_candidate_is_not_packetized` |
| 申告 mode と reason_code の照合 | `test_declared_hold_mode_conflicting_with_reason_code_is_rejected` |
| 3表を1トランザクションにする（canonical の直後に commit を挟む） | `test_ledger_write_rolls_back_completely_on_failure` |
| 冪等判定を `payload_json` から `packet_sha256` へ戻す | `test_reapplying_the_same_result_is_a_noop` |
| 候補の `status` を判断後に動かさない守り | `test_apply_keeps_canonical_facts_and_candidate_status_unchanged` |
| retry 窓の clamp（固定 +14日へ戻す） | `test_ten_day_expiry_retry_window_is_contract_valid` / `test_defer_for_retry_passes_end_to_end_...` |
| LLM の `actor_id` 自己申告を採用する | `test_untrusted_actor_identity_and_timestamp_are_overwritten` |
| canonical fact 表へ1行書く | `test_apply_keeps_canonical_facts_...` ほか計4件 |
| canonical fact writer を import する | `test_structure_does_not_import_canonical_fact_writers` |

2度目の引き取り分（§9 の残り19件）も同じ形で測りました。

| 外した守り | 落ちたテスト |
|---|---|
| `--max-packets` で切るのをやめる | `test_max_packets_limits_count_and_leaves_the_rest_unclaimed` |
| `packet_id` が式に合うかの検証 | `test_forged_packet_id_in_the_packet_file_is_rejected` |
| packet と result の項目照合 | `test_result_with_a_different_source_hash_is_rejected` |
| 判断中の改訂（`packet_stale`）の検知 | `test_candidate_revised_while_judging_is_rejected` |
| `allowed_actions` の検証 | `test_action_outside_allowed_actions_is_rejected` |
| packet ファイル欠落での停止（黙って飛ばす形へ） | `test_result_without_its_packet_file_stops_everything` |
| 他者 claim の除外 | `test_candidate_claimed_by_another_actor_is_skipped` |
| claim の期限判定（期限切れも有効扱い） | `test_expired_claim_is_overwritten_without_deleting_history` |
| `--force-claim` の監査記録 | `test_force_claim_takes_over_and_is_recorded` |
| dry-run 先が本番と同一かの検査 | `test_dry_run_target_must_differ_from_the_production_path` |
| `expires_at` が null のときのフォールバック | `test_candidate_without_expiry_still_builds_a_retry_window` |
| evidence 欠落の判定 | `test_candidate_without_evidence_cannot_defer` |
| 例外の捕捉を `Exception` へ戻す | `test_implementation_errors_are_not_swallowed_as_invalid_results` |

### 測っていて分かった3つの落とし穴

**壊す位置が効く場所とは限りません。** 最初は「明示 `BEGIN` を外す」でロールバックを壊そうとしましたが、Python の sqlite3 は既定で書き込み前に暗黙のトランザクションを開くため、テストは通ったままでした。canonical を書いた直後に `commit()` を挟む形に変えて、はじめて部分書き込みを再現できました。

**別の検査が代わりに弾いていることがあります。** §23（申告 mode と reason_code の不一致）は、当初のテストでは照合を外しても通っていました。再試行候補を渡していなかったので、契約側の「`deferred_retry` なのに候補が無い」検査が先に弾いていたためです。候補を渡す形に直して、照合そのものを測れるようにしました。

**件数だけ見ていると、理由の違いを見落とします。** §15（`allowed_actions` 外の action）も同じ形でした。`requeue` を渡すテストにしていたので、検証を外しても契約側が「agent に `requeue` は許されない」で弾き、捨てられた件数が同じになっていたのです。**捨てた理由（`issue_type`）まで確かめる**ように直しました。「1件捨てられた」で満足せず、なぜ捨てられたかを見ることです。

## 経緯

初回の実装報告では、3ファイルの合計テスト数（55）をこの表の充足件数として扱っていました。これは誤りです。

その後おとが 17〜21・33〜34 を追加し、**残り（1〜5・22〜32・35・51 の通し、および 7〜16・36〜39・43・47〜49・52〜54）はことが引き取って追加しました**。おとのセッションが2度（2時間44分／1時間24分）止まったためで、2026-08-14 の内田さんの判断です。

**この過程で、ことの仕様バグが3件見つかりました。** どれもテストを書いて初めて分かったものです。

1. retry 窓（v1.2 §3.4）— 期限が2週間以内の候補で `next_eligible_at` が窓を追い越し、契約が必ず落ちる
2. 冪等判定（v1.3 §5.3）— `packet_sha256` は `decided_at` 込みなので、再取り込みが必ず衝突扱いになる
3. 候補集合の追跡（v1.4 §3.2）— `packet_sha256` は `targets` を含まないので、どの候補集合を見て判断したかは台帳から辿れない

**3つ目の帰結として、`data/judgment_packets/` の packet ファイルは消さないでください。** 判断の前提を残す唯一の記録です。
