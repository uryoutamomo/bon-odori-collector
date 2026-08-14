# J0-read §9 受け入れ条件のカバー状況

正本仕様は `docs/local-judgment-j0-read-v1.md`（v1.3）。この表がテストの現況の正本です。

**1つのテストが複数の条件を守るのは構いませんが、「テストが通った」ことは条件を満たした証拠になりません。**
`未カバー` は、その条件を守る回帰テストがまだ無いという意味です。正直に書くこと。

| §9 | 守っているテスト |
|---|---|
| 1, 2 | `test_closed_or_held_candidates_are_not_packetized` |
| 3 | `test_superseded_candidate_is_not_packetized` |
| 4 | `test_expired_candidate_is_not_packetized` |
| 5 | `test_candidate_without_queue_row_is_eligible` |
| 6 | `test_packet_ids_are_deterministic_for_identical_row` |
| 7, 8 | **未カバー**（proposal 変更で packet_id が変わる／targets だけ変えると packet_sha256 だけ変わる） |
| 9 | `test_packet_dry_run_writes_report_and_disables_retry_without_occurrence` |
| 10 | `test_allowed_actions_follow_registry` |
| 11 | **未カバー**（`--max-packets` 超過分が出力されず待機件数が出る） |
| 12〜16 | **未カバー**（packet_id の作文・hash 不一致・判断中の改訂・allowed_actions 外・packet ファイル欠落での停止） |
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
| 36〜39 | **未カバー**（claim の排他・期限切れ上書き・release・`--force-claim` の監査） |
| 40 | `test_packet_apply_requires_its_own_confirmation` ほか（dry-run が本番を書き換えない） |
| 41 | `test_packet_apply_requires_its_own_confirmation` / `test_result_apply_requires_its_own_confirmation` |
| 42, 46 | `test_no_auto_migrate_refuses_missing_claim_ledger` |
| 43 | **未カバー**（dry-run の適用先が本番パスと同一なら停止） |
| 44 | `test_both_clis_parse_real_argv` |
| 45 | `test_packet_dry_run_writes_report_and_disables_retry_without_occurrence` |
| 47〜49 | **未カバー**（`--max-packets` の単位・上限で切られた候補が未 claim・レポートの `migrations_applied` と `claim_scope`） |
| 50 | `test_apply_result_writes_ledgers_releases_claim_and_reports` / `test_both_clis_parse_real_argv` |
| 51 | `test_ten_day_expiry_retry_window_is_contract_valid`（窓の計算）＋ `test_defer_for_retry_passes_end_to_end_for_a_candidate_expiring_soon`（取り込みまでの通し） |
| 52〜54 | **未カバー**（expires_at が null／`no_evidence`／実装側の例外が medium に落ちない） |
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

### 測っていて分かった2つの落とし穴

**壊す位置が効く場所とは限りません。** 最初は「明示 `BEGIN` を外す」でロールバックを壊そうとしましたが、Python の sqlite3 は既定で書き込み前に暗黙のトランザクションを開くため、テストは通ったままでした。canonical を書いた直後に `commit()` を挟む形に変えて、はじめて部分書き込みを再現できました。

**別の検査が代わりに弾いていることがあります。** §23（申告 mode と reason_code の不一致）は、当初のテストでは照合を外しても通っていました。再試行候補を渡していなかったので、契約側の「`deferred_retry` なのに候補が無い」検査が先に弾いていたためです。候補を渡す形に直して、照合そのものを測れるようにしました。

## 経緯

初回の実装報告では、3ファイルの合計テスト数（55）をこの表の充足件数として扱っていました。これは誤りです。
その後おとが 17〜21・33〜34 を追加し、**残りの核心群（1〜5・22〜32・35・51 の通し）はことが引き取って追加しました**（おとのセッションが2時間44分停止したため。2026-08-14 内田さんの判断）。
上の「未カバー」19件は、次にまとめて塞ぎます。
