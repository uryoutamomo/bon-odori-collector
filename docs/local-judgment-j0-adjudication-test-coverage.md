# J0-adjudication 受け入れ条件 → テスト対応表

正本＝`docs/local-judgment-j0-adjudication-v1.md`（v1.2、SHA-256 `5da40ca968be2972785791fe74921554e84aca66305bcdfc617e4694614bdd6f`）。
テストは `tests/test_judgment_j0_adjudication.py`（**48本**）。**未カバーはありません（45/45）。**
残る2本は条件番号に紐づかない運用上の守りで、下の「条件外の2本」に書いています。

「合計テスト数」は充足件数ではありません。下の表は条件番号ごとに、どのテストがそれを守っているかと、
**そのテストが「守りを外すと落ちる」ことを実測したか**を記録しています。変異は47通り試し、**47件すべて検知**しました。

| 条件 | テスト | 変異で検知 |
|---|---|---|
| 1 | `test_01_deferred_retry_hold_is_not_listed` | ✓ `hold_mode` の絞りを外す |
| 2 | `test_02_closed_hold_is_not_listed` | ✓ `status='open'` の絞りを外す |
| 3 | `test_03_expired_hold_is_shown_but_not_actionable` | ✓ `expired` を常に False |
| 4 | `test_04_hold_without_packet_file_is_shown_as_undecidable` | ✓ `actionable` から packet 条件を外す |
| 5 | `test_05_hold_claimed_by_another_user_cannot_be_opened` | ✓ 2通り（`claim_other` を False／claim 重複の拒否を外す） |
| 6 | `test_06_agent_claim_does_not_block_the_user` | ✓ claim 種別の判定を外す |
| 7 | `test_07_recording_a_decision_does_not_touch_the_master_rdb` | ✓ 記録時に RDB を1回書く |
| 7a | `test_07a_no_http_path_can_apply_to_the_ledger` | ✓ `/api/adjudication/apply` を生やす |
| 7b | `test_07b_status_reports_pending_count_and_command` | ✓ コマンド文字列を空にする |
| 7c | `test_07_claim_writes_only_the_claim_lease_row` | ✓ claim 時に hold を UPDATE |
| 8 | `test_08_adjudications_are_stored_apart_from_the_legacy_decisions` | ✓ 裁定側から `DECISIONS_PATH` を参照 |
| 9 | `test_09_action_outside_allowed_actions_is_refused` | ✓ `allowed_actions` の検査を削除 |
| 9a | `test_09a_target_outside_the_frozen_candidate_set_is_refused` | ✓ 対象IDの検査を削除 |
| 10 | `test_10_holds_with_a_frozen_candidate_set_cannot_be_batched` | ✓ 一括の候補集合条件を削除 |
| 11 | `test_11_changed_candidate_set_is_invalidated` | ✓ hash 照合を削除 |
| 11a | `test_11a_target_outside_the_candidate_set_is_invalidated_at_apply` | ✓ 反映側の対象検査を削除 |
| 12 | `test_12_decision_on_a_closed_hold_is_invalidated` | ✓ `status='open'` の検査を削除 |
| 13 | `test_13_decision_on_an_expired_hold_is_invalidated` | ✓ 期限検査を削除 |
| 13a | `test_13a_invalidated_rows_keep_their_reason` | ✓ `invalid_reason` を書かない |
| 13b | `test_13b_invalidated_rows_are_not_processed_again` | ✓ `invalidated` も再処理する |
| 13c | `test_13c_an_invalidated_hold_can_be_adjudicated_again_as_a_new_row` | ✓ 失敗時に hold を resolved にする |
| 14 | `test_14_the_three_ledgers_move_together` | ✓ hold の close を削除 |
| 15 | `test_15_apply_goes_through_the_shared_ledger_writer` | ✓ 直接 INSERT を書く |
| 16 | `test_16_a_failure_after_the_decision_leaves_no_partial_write` | ✓ `rollback()` を削除 |
| 17 | `test_17_reapplying_the_same_adjudication_adds_no_ledger_row` | ✓ 冪等判定を常に偽にする |
| 18 | `test_18_applied_rows_carry_the_decision_id_back` | ✓ `decision_id` を書き戻さない |
| 19 | `test_19_the_file_cannot_name_its_own_actor` | ✓ ファイルの `decided_by` を採用 |
| 20 | `test_20_actor_type_and_channel_are_fixed` | ✓ `decision_channel` を llm に差し替え |
| 21 | `test_21_decided_at_is_stamped_by_the_apply_run` | ✓ `recorded_at` を採用 |
| 22 | `test_22_an_eligible_candidate_cannot_be_decided_by_the_user` | ✓ hold 不在を通す |
| 23 | `test_23_a_deferred_retry_hold_cannot_be_decided_by_the_user` | ✓ `hold_mode` の検査を外す |
| 24 | `test_24_batches_never_cross_a_grouping_fingerprint` | ✓ fingerprint 一致条件を外す |
| 25 | `test_25_each_batch_item_is_validated_on_its_own` | ✓ 一括を1行にまとめる |
| 26 | `test_26_the_batch_id_reaches_the_canonical_decision` | ✓ `batch_id` を渡さない |
| 27 | `test_27_a_single_adjudication_has_no_batch_id` | ✓ 単発にも batch_id を付ける |
| 28 | `test_28_canonical_fact_tables_do_not_move` | ✓ `venues` へ1行入れる |
| 29 | `test_29_the_user_lane_imports_no_canonical_fact_writer` | ✓ writer 名を1つ書く |
| 30 | `test_30_the_inbox_status_stays_candidate` | ✓ status を reviewed に更新 |
| 31 | `test_31_legacy_pending_rows_are_untouched` | ✓ pending 行を closed に更新 |
| 32 | `test_32_dry_run_leaves_the_production_database_byte_identical` | ✓ dry-run の書き先を本番にする |
| 33 | `test_33_apply_without_the_confirmation_phrase_is_refused` | ✓ 確認フレーズ検査を削除 |
| 34 | `test_34_apply_never_migrates_and_stops_without_the_ledgers` | ✓ `--apply` でも migration する |
| 34a | `test_34a_dry_run_migrates_only_its_own_copy` | ✓ dry-run の migration を外す |
| 34b | `test_34b_no_auto_migrate_stops_a_dry_run_without_the_ledgers` | ✓ `--no-auto-migrate` を無視 |
| 35 | `test_35_a_dry_run_pointed_at_production_is_refused` | ✓ 同一パス検査を削除 |
| 36 | `test_36_the_real_command_line_drives_every_option` | ✓ `--no-auto-migrate` の定義を削除 |

## 条件外の2本（実際に画面を起動して見つけた守り）

仕様の受け入れ条件には無いが、コンソールを実際に立ち上げて確かめたときに出た問題への守り。

| テスト | 何を守るか |
|---|---|
| `test_06a_a_database_without_the_ledgers_shows_an_empty_lane` | **本番 master RDB には J0 の migration をまだ当てていない。**台帳が無い状態で裁定タブを開いても、`no such table` で画面が落ちず空一覧になること |
| `test_06b_opening_the_lane_never_creates_a_master_database` | `sqlite3.connect` は存在しないパスに**空ファイルを作る**。実際に worktree で裁定タブを開いたら `data/bon_odori_master.sqlite` に0バイトのファイルができた。master RDB の置き場に空の版が残ると、後続のツールがそれを「中身のないマスタ」として開く |

変異の実行手順は `scratchpad/mutate.py` 相当（1件ずつ書き換え → 対象テストだけ実行 → 復元）で、
**毎回 `__pycache__` を消してから測っています**（行長が同じだと古い pyc で誤判定するため）。

## 落とし穴（今回ぶつかった空振り3件。次に同じ形を作らないために）

J0-read で3回空振りしたのと同じことが、今回も**テスト側の弱さとして3件**出ました。いずれも
「テストは通っているのに、守りを壊しても落ちない」状態です。

1. **件数だけ比べると UPDATE を見逃す（条件7c）。** claim が hold を書き換える変異を入れても、
   3台帳の `COUNT(*)` は変わらないので通ってしまいました。**行の中身ごと比べる**ように直しました。
2. **別の検査が先に弾く（条件10）。** 一括の候補集合条件を外しても、その先の「対象IDが要る」で
   `ValueError` になるため `assertRaises` が通り続けました。**例外メッセージまで見る**ように直しました。
3. **壊す場所が効いていない（条件13c）。** dry-run では書き込み先がコピーなので、元DBの hold を見ている
   限り何を壊しても変わりません。**反映先（コピー）の hold を見る**ように直しました。

共通しているのは、**「落ちるはずの変異が落ちなかったとき、テストを疑うか変異を疑うかを切り分ける」**必要があることです。
今回は5件が空振りし、内訳は**テストが弱いもの3件・変異の当て方が悪いもの2件**でした
（存在しない条件へ書いた no-op、NOT NULL 制約で失敗して例外処理に飲まれた INSERT）。
