---
id: L1-review
layer: L1
title: 人のレビュー運用サブシステム
owns:
  - review_inbox.py
  - review_inbox_adapters/**
  - data/review_backlog_decision_overlay.json
  - data/review_backlog_youtube_decision_overlay.json
  - data/review_backlog_event_hold_llm_research.json
  - data/x_candidate_backlog.json
  - data/x_candidate_backlog_alerts.json
  - data/x_candidate_backlog_alerts.md
  - review_console/**
  - review_console_ops/**
  - scripts/promote_change_requests_for_review.py
  - run_review_inbox_rare_signal_scheduled.py
  - run_review_inbox_rare_signal_canary.py
  - run_review_inbox_rare_signal_decision_canary.py
  - run_review_inbox_low_priority_scheduled.py
  - run_review_inbox_x_gap_scheduled.py
  - x_candidate_backlog.py
  - build_rare_signal_backcheck_queue.py
  - search_rare_signal_backcheck_sources.py
  - export_rare_signal_backcheck_reviews.py
  - stage_rare_signal_backcheck_reviews.py
  - build_historical_reference_quality_review.py
  - build_x_review_lanes.py
  - build_x_account_console.py
  - build_x_news_digest_for_oto.py
  - promote_x_news_digest_reviews.py
  - review_x_candidate_posts.py
  - build_event_poster_ocr_queue.py
  - build_retrospective_harvest.py
  - build_weekly_harvest_candidates.py
  - prepare_weekly_harvest_review.py
  - build_official_source_review.py
  - review_inbox_migration_runner.py
  - docs/x-candidate-backlog-operations.md
depends_on:
  - L1-master
invariants:
  - INV-RVW-001
  - INV-RVW-002
  - INV-RVW-003
  - INV-RVW-004
  - INV-RVW-005
  - INV-RVW-006
  - INV-RVW-007
  - INV-RVW-008
  - INV-RVW-009
  - INV-RVW-010
  - INV-RVW-011
  - INV-RVW-012
  - INV-RVW-013
  - INV-RVW-014
  - INV-RVW-015
  - INV-RVW-016
  - INV-RVW-017
  - INV-RVW-018
  - INV-RVW-019
  - INV-RVW-020
  - INV-RVW-021
  - INV-RVW-022
  - INV-RVW-023
verified_by:
  - tests/test_review_inbox_decision_writer.py
  - tests/test_promote_change_requests_for_review.py
  - tests/test_judgment_j0_adjudication.py
  - tests/test_e0b_bridge.py
  - tests/test_e2_identity_judgment.py
  - tests/test_judgment_j0_read.py
  - tests/test_x_song_resolution_contract.py
  - tests/test_x_occurrence_resolution_contract.py
  - tests/test_review_console.py
  - tests/test_review_inbox_low_priority_adapters.py
  - tests/test_review_inbox_youtube_adapter.py
  - tests/test_x_candidate_backlog.py
  - tests/test_run_review_inbox_x_gap_scheduled.py
  - tests/test_ward_official_source_registry.py
updated_for: a47769f
---

# 人のレビュー運用サブシステム

> 上位は[全体地図](../README.md)。下流は[マスタ](04-master.md)。

## この工程は何のためにあるか

機械が決められないものを、人が裁定する工程である。
断片から「この投稿はこのイベントの告知だ」「この会場はここだ」と決めきれないものが必ず残るので、
それを受信箱に積み、レビューコンソールで人が判断し、決定をマスタへ渡す。

**盆助全体の律速はここにある。** 集めることでも判断することでもなく、
人が裁定を下す速度が全体の速度を決めている。実際、精度が悪いように見える場面を追いかけると、
判定アルゴリズムではなく**人のレビューが詰まっている**ことのほうが多い。
「精度が悪い」と感じたら、まず止まっている工程を探すのが正しい順序になる。

もうひとつ、この工程には性質上の難しさがある。人の判断は繰り返せない。
同じ画面をもう一度開いて同じ操作をしたときに、決定が二重に適用されたり、
裁定した相手が別のイベントにすり替わっていたりすると、人は自分の判断を信用できなくなる。
だから設計の重心は「詰まらせないこと」と「決定を取り違えないこと」の2つに置かれている。

## 入力と出力

**入力**

| 何を | どこから |
|---|---|
| 各種の要レビュー項目 | `review_inbox_adapters/` 配下の各アダプタ経由（X由来の穴、公式ソース、会場欠落、過去実績、YouTube など） |
| 現在のマスタ状態 | Master RDB の `review_inbox_items` テーブル |

**出力**

| 何を | どこへ |
|---|---|
| 受信箱の投影 | `data/review_inbox.json` |
| X候補の永続ライフサイクルと日次アラート | `data/x_candidate_backlog.json` / `data/x_candidate_backlog_alerts.*` |
| 人の決定 | `review_inbox_items` の状態更新 |
| 適用可能な変更リクエスト | 昇格済みの reviewed JSON → [マスタ](04-master.md) |

## 不変条件

### INV-RVW-001 同じ決定を二度書いても、二重に適用されない

- **内容**: 決定の書き込みは1項目につき1つのライフサイクルだけを発行する。
  まったく同じ決定を再送した場合は noop として扱い、何も起きない。
- **なぜ**: 人はブラウザを再読み込みするし、通信は失敗する。
  再試行が二重適用になる設計だと、人が安心して操作できない。
- **破れたときの症状**: 1回の裁定が2件の変更として適用される。件数が合わなくなる。
- **守っているコード**: `review_inbox_adapters/decision_writer.py`
- **守っているテスト**: `tests/test_review_inbox_decision_writer.py::test_decision_write_publishes_one_lifecycle_only_then_exact_retry_is_noop`、
  `tests/test_review_inbox_decision_writer.py::test_existing_decision_requires_exact_lifecycle_for_noop`

### INV-RVW-002 対象の取り違えと競合は、通さずに止める（fail-closed）

- **内容**: 決定を書くとき、対象の同一性が一致しない場合と、
  比較対象の状態が変わっていた場合（CAS衝突）は、書き込まずに失敗させる。
- **なぜ**: 人が見た画面と、実際に書き込まれる対象がズレていると、
  **裁定そのものが別のイベントに適用される**。これはデータが壊れるより悪い。
  人が「自分は正しく判断した」と思っているのに結果が違う、という形で信頼を壊すからだ。
  迷ったら書かない側に倒すのが正しい。
- **破れたときの症状**: レビューした覚えのないイベントの情報が変わっている。
- **守っているコード**: `review_inbox_adapters/decision_writer.py`
- **守っているテスト**: `tests/test_review_inbox_decision_writer.py::test_target_identity_and_cas_conflict_fail_closed`

### INV-RVW-003 決定の書き込みが、勝手にスキーマを移行しない

- **内容**: 決定writerは、受信箱スキーマが古い版だった場合に自動で移行しない。
- **なぜ**: 移行は専用のworkflow（`migrate_review_inbox_v2.yml`）の仕事で、
  日常の書き込み経路が副作用としてスキーマを変えると、いつ変わったのか誰も追えなくなる。
  マスタ側で起きた [INV-MST-005](04-master.md) の事故と同じ構図で、
  「動いているように見えて、別の工程が壊れる」種類の問題につながる。
- **破れたときの症状**: 意図しないタイミングでスキーマが変わり、他の工程が失敗し始める。
- **守っているコード**: `review_inbox_adapters/decision_writer.py`
- **守っているテスト**: `tests/test_review_inbox_decision_writer.py::test_writer_never_migrates_v1_schema`

### INV-RVW-004 実適用に使う reviewed JSON は、人の昇格を経たものだけ

- **内容**: 自動生成された reviewed JSON は機械検査専用で、人レビュー済みとして扱わない。
  実際に適用する JSON は `scripts/promote_change_requests_for_review.py` を人が実行して作り、
  レビュー担当者と経緯を記録する。承認IDが未知のもの、`dry_run_only` が付いていない選択は拒否される。
- **なぜ**: 「レビュー済み」という印は、人が見たことの証明でなければ意味がない。
  機械が付けた印を人の印と同じ扱いにすると、レビュー工程そのものが形骸化する。
- **破れたときの症状**: 誰も見ていない変更が「レビュー済み」としてマスタへ入る。
- **守っているコード**: `scripts/promote_change_requests_for_review.py`
- **守っているテスト**: `tests/test_promote_change_requests_for_review.py::test_refuses_unknown_approved_id`、
  `tests/test_promote_change_requests_for_review.py::test_refuses_selected_request_without_dry_run_only`

### INV-RVW-005 J0-read は正本factを変更しない

- **内容**: event candidate の packet 化と LLM 判断の取り込みは、canonical decision / queue / hold / claim の台帳だけへ記録する。venue、series、occurrence、song とその alias/link 表は変更しない。
- **守っているコード**: `build_judgment_packets.py`、`apply_judgment_results.py`、`judgment_ledger_writer.py`
- **守っているテスト**: `tests/test_judgment_j0_read.py::test_apply_keeps_canonical_facts_and_candidate_status_unchanged`、`tests/test_judgment_j0_read.py::test_structure_does_not_import_canonical_fact_writers`

### INV-RVW-006 LLMの自己申告は判断主体にしない

- **内容**: actor identity・channel・時刻はローカルentrypointが stamp し、result JSON の申告値は採用しない。
- **守っているテスト**: `tests/test_judgment_j0_read.py::test_untrusted_actor_identity_and_timestamp_are_overwritten`

### INV-RVW-007 J0-read はcandidateを消費しない

- **内容**: `review_inbox_items.status` は `candidate` のまま維持する。E0 の改訂・再実行を止めないためである。
- **守っているテスト**: `tests/test_judgment_j0_read.py::test_apply_keeps_canonical_facts_and_candidate_status_unchanged`

### INV-RVW-008 裁定画面のボタンは判断台帳を動かさない

- **内容**: 裁定タブの操作が master RDB へ書けるのは `review_claim_ledger` のリース行だけで、canonical decision / queue / hold の3台帳は行の中身まで含めて不変である。台帳への反映は確認フレーズ付きCLI（`apply_user_adjudications.py --apply`）だけが行い、**それを呼ぶ HTTP パスを置かない**。UIのボタンに確認フレーズを肩代わりさせないためである。
- **守っているコード**: `review_console/data.py` の裁定ヘルパ群、`review_console/server.py`
- **守っているテスト**: `tests/test_judgment_j0_adjudication.py::test_07_recording_a_decision_does_not_touch_the_master_rdb`、`tests/test_judgment_j0_adjudication.py::test_07_claim_writes_only_the_claim_lease_row`、`tests/test_judgment_j0_adjudication.py::test_07a_no_http_path_can_apply_to_the_ledger`

### INV-RVW-009 人が裁けるのは agent が開いた awaiting_user の hold だけ

- **内容**: user の terminal decision は、`status='open'` かつ `hold_mode='awaiting_user'` の hold を経たものに限る。hold の無い候補（eligible）と `deferred_retry` の hold へは、画面からも反映CLIからも裁定を通さない。人の経路を全pendingへの並行入口にすると、判断待ち561件の器が二重になるためである。
- **守っているコード**: `review_inbox_adapters/apply_user_adjudications.py` の `_validate`、`local_judgment_contract.build_user_decision`
- **守っているテスト**: `tests/test_judgment_j0_adjudication.py::test_22_an_eligible_candidate_cannot_be_decided_by_the_user`、`tests/test_judgment_j0_adjudication.py::test_23_a_deferred_retry_hold_cannot_be_decided_by_the_user`

### INV-RVW-010 裁定の対象は凍結された候補集合の中からしか選べない

- **内容**: 反映時に hold の `candidate_set_sha256` を照合し、一致しない裁定は `invalidated` にする。`target_id` は hold の `candidate_ids` に含まれるものに限り、候補集合が空の hold には対象を付けられない。対象の要否は `candidate_ids` の有無で決める（`required_resolution_type` は hold_mode から決まる2値で、対象の要否を表さない）。
- **守っているコード**: `review_console/data.py` の `adjudication_target_required` / `_check_target`、`apply_user_adjudications.py` の `_validate`
- **守っているテスト**: `tests/test_judgment_j0_adjudication.py::test_11_changed_candidate_set_is_invalidated`、`tests/test_judgment_j0_adjudication.py::test_09a_target_outside_the_frozen_candidate_set_is_refused`、`tests/test_judgment_j0_adjudication.py::test_11a_target_outside_the_candidate_set_is_invalidated_at_apply`

### INV-RVW-011 コンソール由来の変更提案は、人の昇格なしに適用JSONへ落ちない

- **内容**: `build_change_requests_from_review_inbox.build_requests()` が返すリクエストは全件 `dry_run_only` を持つ。つまり `apply_change_requests --apply` は必ず拒否し、`scripts/promote_change_requests_for_review.py` が人の昇格（`reviewed_by` / `reviewed_at`）を刻んだ後でしか適用できない。あわせてこの橋渡しは既定で `review_console_change_request` レポートを書き、コンソールの選択が候補器（E0）経由でも進めるようにする。
- **なぜ**: コンソールの `confirm_current_date` / `promote_historical_reference` / `fill_venue` は、判断台帳を1行も通さずに master RDB の正本factへ到達できる唯一の経路だった。旧経路を消さずに（strangler）、適用の直前へ人の関門を1つ入れる。
- **破れたときの症状**: 画面で押した選択が、誰の確認も決定記録もないまま開催回の日付・会場・過去実績を書き換える。
- **守っているコード**: `review_inbox_adapters/build_change_requests_from_review_inbox.py` の `build_requests()` と `build_candidate_reports()`
- **守っているテスト**: `tests/test_e0b_bridge.py::test_every_built_request_is_dry_run_only`、`tests/test_e0b_bridge.py::test_apply_layer_refuses_bridge_output`、`tests/test_e0b_bridge.py::test_cli_writes_candidate_reports_by_default`

### INV-RVW-012 LLMは同一性だけを答え、事実を書かない

- **内容**: event レーンの `accept` / `hold` の payload に許すのは、同一性の答え3つ（`occurrence_match` / `series_match` / `venue_match`）と共通項目だけである。イベント名・日付・会場名・IDの新規値・状態値が payload に現れたら validator が拒否する。song / term レーンの payload 集合は変えない。
- **なぜ**: LLMは全体像を見渡すのが苦手なので、一つの業務をシンプルに保つ。事実は E0 が抽出済みなので、判断者に言い直させると同じ事実の食い違う写しが2つできる。
- **破れたときの症状**: 候補と判断で名前や日付が食い違い、どちらが正しいか分からなくなる。
- **守っているコード**: `review_inbox_adapters/local_judgment_contract.py` の `_payload_fields()` と `ACTION_REGISTRY`
- **守っているテスト**: `tests/test_e2_identity_judgment.py::test_identity_fields_are_allowed_on_event_lanes`、`tests/test_e2_identity_judgment.py::test_song_and_term_payload_fields_are_unchanged`、`tests/test_e2_identity_judgment.py::test_event_facts_in_the_payload_are_rejected`

### INV-RVW-013 新しい系列・会場が生まれる答えは、人の確認を経る

- **内容**: `series_match` または `venue_match` が `"none"` の判断は、機械が `awaiting_user` の hold へ落とす（reason code は `new_series_requires_confirmation` / `new_venue_requires_confirmation`）。裁定を経ていないものは変更要求へ変換しない。開催回だけが `"none"` の場合は止めない。
- **なぜ**: 系列と会場は重複しても統合（merge）の仕組みがまだ無く、取り消せない。開催回の追加は `occurrence_id` で後から直せるので、止める必要がない。保留にするのは機械側の運用ポリシーで、LLMの判断そのものは payload に残る——統合が実装されたらポリシーだけ外せばよい。
- **破れたときの症状**: 同じ行事の系列や同じ場所の会場が、誰も見ないまま二重に増える。
- **守っているコード**: `review_inbox_adapters/apply_judgment_results.py` の `_identity_hold_reason()`、`build_change_requests_from_judgment.py` の抽出条件
- **守っているテスト**: `tests/test_e2_identity_judgment.py::test_new_series_answer_becomes_an_awaiting_user_hold`、`tests/test_e2_identity_judgment.py::test_new_venue_answer_becomes_an_awaiting_user_hold`、`tests/test_e2_identity_judgment.py::test_unadjudicated_none_is_not_converted`

### INV-RVW-014 同一性の答えは候補集合の中からしか選べない

- **内容**: `occurrence_match` / `series_match` / `venue_match` は、パケットに提示した候補に含まれるIDか `"none"` のいずれかに限る。`occurrence_match` を指したなら `series_match` はその開催回の系列と一致しなければならない。新規確認の hold では候補集合を凍結しない（対象を選ぶ hold ではないため。対象IDは要求されず、一括で裁ける）。
- **なぜ**: 候補の外のIDを通すと、見てもいない開催回が書き換わる。
- **破れたときの症状**: 無関係の行事に日付や会場が付く。裁定画面で選べない対象を要求される。
- **守っているコード**: `review_inbox_adapters/apply_judgment_results.py` の `_identity_problem()` と `candidate_ids` の決定
- **守っているテスト**: `tests/test_e2_identity_judgment.py::test_identity_outside_the_candidate_set_is_rejected`、`tests/test_e2_identity_judgment.py::test_series_match_conflicting_with_occurrence_is_rejected`、`tests/test_e2_identity_judgment.py::test_new_confirmation_hold_needs_no_target_and_can_be_batched`

### INV-RVW-015 判定に見せる候補集合は判定直前に引き直し、取り込み時に照合する

- **内容**: 判定用パケットの `targets` は、E0 が候補化した時点のものではなく**パケット生成時にDBから引き直す**。パケットは候補集合の指紋（`candidate_set_sha256`）を持ち、取り込み時に同じ検索をやり直して照合する。一致しなければ `candidate_set_changed` で受け取らない。
- **なぜ**: 候補集合は `source_payload_hash`（提案の中身）の材料ではないので、**E0 を何度回しても更新されない**。候補化から判定までに日が空くほど古くなり、日次収集で開催回が増えていても判定者には見えない。既存の陳腐化検査は提案の中身しか見ないため、古い候補集合での判断がそのまま通る。2026-08-15 の実地試行では、8日前のコピーで判定した20件のうち**10件が「どれとも違う（＝新規）」と誤判定**され、そのまま入れていれば重複イベントが10件生まれていた（系列の統合はまだ無く、取り消せない）。
- **破れたときの症状**: 既にあるイベントが「新規」と判断され、重複した系列が増える。判断の根拠になった候補集合が、実際の状態と食い違う。
- **守っているコード**: `review_inbox_adapters/build_judgment_packets.py` の `refreshed_row()` と `candidate_set_hash()`、`apply_judgment_results.py` の照合
- **守っているテスト**: `tests/test_judgment_j0_read.py::test_packet_refreshes_the_candidate_set_from_the_database`、`tests/test_judgment_j0_read.py::test_a_changed_candidate_set_is_refused_at_ingest`、`tests/test_judgment_j0_read.py::test_an_unchanged_candidate_set_is_accepted`

### INV-RVW-016 名指しされた対象は判定者に見せ、材料の無い候補を「新規」として人へ回さない

- **内容**: レポートが開催回IDを名指ししている候補（`explicit_occurrence_id`。公式お知らせの `confirm_existing` 由来）は、名前を持たず検索に掛からなくても、その開催回と会場を候補集合の先頭に入れる（統合済み `lifecycle_status='merged'` は除く）。あわせて、同一性が `"none"` でも**新規を作る材料（イベント名／会場名）が無ければ** `new_series_requires_confirmation` / `new_venue_requires_confirmation` ではなく `insufficient_evidence` を理由にする。
  ただし既存開催回を選択済みで、新しい会場名の提案も無い場合は、その開催回が持つ会場で対象が一意なので、
  `venue_match="none"` だけを理由に人へ回さない。
- **なぜ**: `confirm_existing` の候補は開催回IDだけを持ち、名前も年も会場名も持たないことが多い（2026-08-15 の実データで112件中55件）。候補集合が空になるため判定者は `"none"` としか答えられず、機械はそれを「新規です」と解釈して人の確認へ回す。ところが**新規を作る材料が無いので、裁定しても何も生まれない**。実際、この日の保留56件は全件が名前も会場名も空で、裁定画面を開いても人は何も判断できなかった。
- **破れたときの症状**: 対象が分かっているのに「どれとも違う」と判断される。名前も会場も空の項目が裁定待ちに積み上がり、人が見ても処理できない。
- **守っているコード**: `review_inbox_adapters/build_event_inbox_candidates.py` の `search_targets()`、`apply_judgment_results.py` の `_identity_hold_reason()`
- **守っているテスト**: `tests/test_e2_identity_judgment.py::test_named_occurrence_is_offered_even_without_a_name`、`tests/test_e2_identity_judgment.py::test_a_merged_occurrence_is_not_offered`、`tests/test_e2_identity_judgment.py::test_no_name_yields_insufficient_evidence_not_new_series`、
  `tests/test_e2_identity_judgment.py::test_selected_occurrence_without_a_new_venue_needs_no_user_hold`

### INV-RVW-017 X曲同定の判断取込は正本factを書かず、見せた候補全体を凍結する

- **内容**: 曲retrieval/noveltyと開催回同定は別packetにし、観測、候補行、catalog/occurrence snapshot、
  allowed actionをSHAへ含める。回答取込は各decision台帳だけへappendし、actor/model/prompt/timeをローカルでstampする。
  event dependencyは同じfamilyの最大revisionだけを見る。同じsnapshotでdecision済みのpacketは再提示せず、
  解決済みidentityは選択行が変わらない限り無関係なentity追加で開き直さない。
- **なぜ**: ID列だけのhashでは、判定者が見たtitle・alias・年・日付・会場が後から変わっても回答が通る。
  また旧revisionのacceptを使うと、訂正・reject済みイベントへ曲を結べる。
- **破れたときの症状**: stale回答が別曲・別年の開催回へ適用される。判断を取り込んだだけで公開factが増える。
- **守っているコード**: `review_inbox_adapters/x_song_resolution_contract.py`、
  `review_inbox_adapters/x_occurrence_resolution_contract.py`
- **守っているテスト**: `tests/test_x_song_resolution_contract.py`、
  `tests/test_x_occurrence_resolution_contract.py::test_event_dependency_never_reuses_accept_from_an_older_revision`、
  `tests/test_x_occurrence_resolution_contract.py::test_resolved_occurrence_is_not_reopened_by_unrelated_snapshot_change`

### INV-RVW-018 レビュー画面の自動解決は、完全な現在集合か一意な確定開催回だけを根拠にする

- **内容**: 統合受信箱のpending行を表示上の処理済みにできるのは、`selection.mode=all` の完全スナップショットを
  リポジトリ内で再現でき、その現在集合から安定IDが消えた場合、またはX新規イベント候補について
  シリーズ名・開催年・開催日が一致する確認済み公開イベントがちょうど1件ある場合だけである。
  入力欠落・変換失敗・複数一致では候補を隠さない。この表示上の解決は受信箱DBのstatus/decisionを変更しない。
- **なぜ**: source writerは監査のため、元キューから消えたpending行もDBに残す。そのまま全件を人へ見せると
  解決済みの残骸が現在の仕事を埋める。一方、canaryや部分スナップショットからの不在を「解決」とみなすと、
  まだ必要なレビューを消してしまうため、完全性と一意な同一性を証明できる場合に限る。
- **破れたときの症状**: もう候補でない行が未レビュー件数を増やし続ける。逆に、別イベントや未収集の行が
  勝手に処理済みになり、必要な確認が画面から消える。
- **守っているコード**: `review_console/data.py` の `current_complete_source_inbox_ids()`、
  `source_snapshot_auto_resolution()`、`x_gap_public_auto_resolution()`
- **守っているテスト**: `tests/test_review_console.py::ReviewConsoleTests::test_review_inbox_item_absent_from_complete_current_source_snapshot_is_closed`、
  `tests/test_review_console.py::ReviewConsoleTests::test_x_gap_new_event_already_confirmed_in_public_data_is_closed`

### INV-RVW-019 判断済み候補は、安定IDと内容の指紋が一致するときだけ現在集合から外す

- **内容**: 曲・用語/曲×会場・会場・YouTube曲証拠候補の人/LLM判断は、元JSONのライフサイクル欄へ
  偽装して書き戻さず、`data/review_backlog_decision_overlay.json` と
  `data/review_backlog_youtube_decision_overlay.json` に判断主体と理由を残す。完全スナップショットを作る際、
  `source_id`・`source_key`・`inbox_id`・`source_payload_hash` が現在候補とすべて一致した判断だけを除外する。
  `保留` は完了判断ではないためoverlayでは受理せず、待ち一覧に残す。
  安定IDが違えば fail-closed、内容の指紋が変わればその判断を stale として候補を再提示する。
  YouTube入力はリポジトリ内の版よりDB側が新しい場合があるため、画面上の自動解決はDB行の4項目が
  overlayと完全一致する行だけに限り、古いファイルからの不在を根拠にしない。
  この処理は受信箱DBのstatus/decisionと曲・用語・会場の正本factを変更しない。
- **なぜ**: 2026-08-18の監査では低優先29件のうち、曲3件と会場5件は別ファイルですでに人が判断済み、
  用語1件も登録済みだった。生成キューが判断記録を引き継がず、同じ意味の候補を別の証拠URLで再発行していたため、
  LLMに同じ問いを繰り返すだけでなく「レビュー待ち」の実数も水増ししていた。一方、語だけで過去判断を再利用すると、
  根拠や意味が変わった別候補まで隠すため、判定時の内容全体の指紋を必須にする。
  同日のYouTubeパイロット43件も同じ契約で凍結し、DB未同期の新着とDB側で内容が変わった行を
  古い判断で閉じないようにした。
  続く全件処理では、当時の現在集合に残った505件（YouTube 247、過去実績60、公開差分197、X 1）を
  同じ完全一致契約で凍結した。公開差分は、曲名84件を既存曲へ統合、55件をタイトル断片として除外、
  8件を新規曲候補として維持し、2026年日程の直接根拠が無い38件は今年の日付へ転用しなかった。
  公開辞書未同期12件の `公開同期対象` とX 1件の `公式確認待ち` も、正本factを変更する指示ではなく、
  現在入力に対するレビュー完了分類である。
- **破れたときの症状**: 判断済みの曲・会場が日次で再び待ち一覧へ現れる。逆に、証拠内容が変わった候補が
  過去判断で勝手に消える。LLM判断が人判断として記録される。
- **守っているコード**: `review_inbox_adapters/backlog_decision_overlay.py`、
  `review_inbox_adapters/low_priority_adapters.py` と `review_inbox_adapters/youtube_adapter.py` の `build_snapshot()`、
  `review_console/data.py` の `decision_overlay_auto_resolution()`、
  `scripts/build_publication_gap_song_identity_llm_decisions.py`、
  `scripts/build_review_backlog_completion_overlays.py`
- **守っているテスト**: `tests/test_review_inbox_low_priority_adapters.py::test_exact_decision_overlay_closes_only_the_frozen_payload`、
  `tests/test_review_inbox_low_priority_adapters.py::test_decision_overlay_fails_closed_on_identity_or_vocabulary_errors`、
  `tests/test_review_inbox_youtube_adapter.py::ReviewInboxYouTubeAdapterTest::test_frozen_agent_decision_filters_only_the_exact_youtube_payload`、
  `tests/test_review_console.py::ReviewConsoleTests::test_exact_overlay_decision_is_attributed_to_agent_and_stale_hash_stays_open`、
  `tests/test_review_backlog_llm_completion.py`

### INV-RVW-020 既存開催回へ完全一致した古い人待ちholdは、内容が変わらない間だけ画面から外す

- **内容**: `data/review_backlog_event_hold_llm_research.json` に凍結した重複判断は、hold ID、inbox ID、
  source payload hash、prior agent decision ID、元タイトル、明示された開催回ID、系列ID、会場ID、開始日が
  現行DBとすべて一致するときだけ、裁定タブの現在集合から外す。prior agentの回答も
  `occurrence_match` / `series_match` が同じ対象で `venue_match="none"` だったこと、候補payloadの
  `explicit_occurrence_id` / `resolved_target` が同じ開催回を指すことまで照合する。どれか1つでも変われば
  fail-closedで人待ちへ再表示する。この投影はhold/queue/decision台帳と正本factを変更しない。
- **なぜ**: 2026-08-18の監査では人待ち48件すべてが、既存開催回と系列を正しく選択済みなのに、
  会場候補が空だったため `venue_match="none"` となり `insufficient_evidence` holdへ落ちていた。
  47件は名称・会場・開始日まで既存published occurrenceと完全一致し、残る1件も明示開催回ID・名称・会場が一致した。
  人へ採否を尋ねても新しい情報は得られず、同じ対象を二重に確認するだけだった。
- **破れたときの症状**: 既存イベントのdetail修正48件が人の採否待ちとして残る。逆に、開催回や元候補が
  更新された後も古いLLM判断でholdが隠れる。
- **守っているコード**: `review_inbox_adapters/event_hold_decision_overlay.py`、
  `review_console/data.py` の `load_adjudication_holds()`、
  `review_inbox_adapters/apply_judgment_results.py` の `_identity_hold_reason()`
- **守っているテスト**: `tests/test_judgment_j0_adjudication.py::JudgmentJ0AdjudicationTest::test_06c_exact_llm_duplicate_overlay_removes_only_the_matching_hold`、
  `tests/test_e2_identity_judgment.py::MissingMaterialTest::test_selected_occurrence_without_a_new_venue_needs_no_user_hold`

### INV-RVW-021 X候補の件数上限は表示量だけを制限し、候補自体を捨てない

- **内容**: `x_candidate_backlog.py` は `build_x_gap_candidates.py` の `candidates` と
  `archived_candidates` を毎日どちらも `data/x_candidate_backlog.json` へ合流する。前日の候補が
  今日の30件から消えても台帳から削除せず、`未処理 / 処理中 / 登録済み / 却下` の状態を保持する。
  terminal状態は根拠・主体つきの明示transitionなしに再開しない。開催日が近い候補と公式候補を
  選出順で優先するが、低優先候補を消さない。
- **なぜ**: 旧経路では公式新規5件・全体30件の上限超過分を毎日作り直し、同じ古い候補が先頭に
  残って後続が永久に選ばれなかった。上限は人の処理量を守るために必要だが、持ち越し状態が無いと
  「処理を遅らせる」が「情報を捨てる」に変わる。
- **破れたときの症状**: `archived_count` は増えるのに翌日の未処理件数へ反映されず、開催直前の
  未登録イベントが内田さんの名指し調査まで見つからない。
- **守っているコード**: `x_candidate_backlog.py` の `build_backlog()`、`transition_status()`、
  `select_daily_cohort()`
- **守っているテスト**: `tests/test_x_candidate_backlog.py::test_overflow_is_persisted_and_terminal_lifecycle_survives_next_merge`、
  `tests/test_x_candidate_backlog.py::test_due_soon_and_official_candidates_are_prioritized_then_selected_five`

### INV-RVW-022 X候補の日次5件は部分コホートとしてCAS成功後だけ処理中にする

- **内容**: 日次投入は最大5件で、adapter snapshotに `selection.mode=cohort` を明記する。
  `all`（完全スナップショット）や1件だけの `canary` と偽らない。`run_review_inbox_x_gap_scheduled.py` は
  repository variable、明示environment、CAS、parity、公開投影不変を全て通した後だけ、同じ5件を
  バックログの `処理中` へ移す。失敗時は `未処理` のまま次回へ残す。信頼度別の自動反映方針は
  台帳に記録するが、canary期間中は `automatic_publication_enabled=false` で正本factを変更しない。
- **なぜ**: 部分集合の不在を「現在の全候補から消えた」と誤認すると、以前に積んだpending行を
  レビュー画面から隠してしまう。先に処理中へ動かすと、S3/CAS失敗だけで候補が再選出されなくなる。
- **破れたときの症状**: 受信箱へ入っていない候補が処理中になって止まる、または今日の5件に
  含まれなかった過去候補が自動解決扱いで画面から消える。
- **守っているコード**: `review_inbox_adapters/x_gap_adapter.py` の
  `build_daily_cohort_snapshot()`、`run_review_inbox_x_gap_scheduled.py` の `run_scheduled()`、
  `review_inbox_adapters/source_writer.py` の cohort gate
- **守っているテスト**: `tests/test_x_candidate_backlog.py::test_daily_snapshot_is_an_explicit_partial_cohort_and_queueing_is_post_write`、
  `tests/test_run_review_inbox_x_gap_scheduled.py::test_scheduled_cohort_writes_five_and_only_then_marks_them_in_progress`、
  `tests/test_run_review_inbox_x_gap_scheduled.py::test_cas_conflict_leaves_candidates_unprocessed`

### INV-RVW-023 新規会場の確認済み23区は変更要求まで欠落なく運ぶ

- **内容**: E2の同一性判定で新規会場を選び、人のacceptを経て変更要求へ変換するとき、`proposal.venue.area` が東京23区の正規名なら `venue.name` と一緒に運ぶ。空欄・23区外・自由記述は運ばず、既存会場を選んだ枝は従来どおり `venue_id` だけを運ぶ。
- **なぜ**: E0XとE2が区を保持していても、`_venue_block()` が名前だけへ縮めると書き込み直前に区が消え、確定済み開催回が公開の23区フィルタから黙って落ちる。下流で町名や駅名から推測するのではなく、レビュー済みの構造化値を失わず渡す必要がある。
- **破れたときの症状**: E2パケットには8会場すべての区があるのに、change requestと `venues.area` は空になり、公開イベントが1件も増えない。
- **守っているコード**: `review_inbox_adapters/build_change_requests_from_judgment.py` の `_venue_block()`
- **守っているテスト**: `tests/test_e2_identity_judgment.py::ConversionTest::test_new_venue_carries_only_a_canonical_tokyo_23_area`、`tests/test_e2_identity_judgment.py::ConversionTest::test_user_acceptance_of_a_new_series_becomes_create_event_series`、`tests/test_e2_identity_judgment.py::CreateEventSeriesTest::test_create_event_series_persists_the_reviewed_venue_area`

## 主要な流れ

1. **各アダプタが受信箱へ積む** — `review_inbox_adapters/` 配下。X由来の穴、公式ソース、
   会場欠落、過去実績、YouTube など、種類ごとに別アダプタになっている。
   **アダプタが守る形と禁止事項は[受信箱アダプタの契約](../L2/review-inbox-adapter.md)にある**
   （`source_adapter.py` と `parity.py` を触るときは、このL1ではなくそちらのINV-ADPを読む。
   ファイルの持ち主はこのL1のままなので、逆引きからは片道にしか繋がらない）。
2. **受信箱を投影する** — `review_inbox.py --out-json data/review_inbox.json --status pending`。
3. **人が裁定する** — `review_console_ops/run_review_console.py` でローカルサーバを立て、
   `review_console/` のUIで判断する。
4. **決定を書く** — `review_inbox_adapters/decision_writer.py`（INV-RVW-001〜003）。
5. **昇格させる** — `scripts/promote_change_requests_for_review.py` を人が実行（INV-RVW-004）。
6. **マスタへ適用** — [L1-master](04-master.md) の dry-run → apply 経路へ。

### J0-read の局所判断経路

E0 が作った `status='candidate'` を `build_judgment_packets.py` が claim 付きpacketへ凍結する。LLM の result は `apply_judgment_results.py` が packet/source hash/allowed action を照合してから正規化し、`judgment_ledger_writer.py` が decision・queue・hold の3台帳へだけ書く。これは正本factへの適用経路ではない。retry候補、actor identity、時刻をLLMに決めさせると再試行や監査が壊れるため、機械計算またはローカルentrypointの値だけを採用する。

### J0-adjudication の user 裁定レーン

agent が `awaiting_user` hold を開いた候補だけを、同じレビューコンソール（`http://127.0.0.1:8751/` の「裁定」タブ、ショートカット `b`）で人が判断する。画面操作は `data/review_console/adjudications.json` に記録するだけで、判断の台帳は動かさない（唯一の例外は `review_claim_ledger` の作業中リース行）。反映は `apply_user_adjudications.py --apply` の確認フレーズ付きCLIに限定し、それを呼ぶHTTPパスは置かない。反映時はholdの候補集合hash、期限、allowed action、対象IDが候補集合の内側かを再照合し、`build_user_decision` と既存 `judgment_ledger_writer.write_decision` を通す。失敗した記録は消さず `invalidated` と理由を残し、holdは open のままなので裁き直せる。J0-read同様、canonical fact表と `review_inbox_items.status` は変更しない。

既存開催回への完全一致を別途凍結できた古いholdは、INV-RVW-020の全項目が一致する間だけ裁定タブから除外する。
これはDB上のholdを閉じる操作ではなく、人が今判断すべき集合の投影である。

**裁定で「採用」してもイベントは1件も増えない。** 記録が台帳へ入るだけで、正本factへの反映はE2a以降である。

### E0b のコンソール橋渡し

コンソールで `confirm_current_date` / `promote_historical_reference` / `fill_venue` を選ぶと、`decision_stage.py` が
`data/review_console/staged/review_inbox_change_request_decisions.json` へ落とす。`build_change_requests_from_review_inbox.py` は
これを2通りに書き出す。1つは E0 の候補器が読む `review_console_change_request` レポート（既定・`--no-candidate-report` で抑止）で、
判断台帳を通る新しい経路になる。もう1つは従来の change request JSON で、こちらは全件 `dry_run_only` 付きなので昇格を経ないと適用できない
（INV-RVW-011）。**コンソールの選択は「決定」ではなく「提案」として候補になる**——契約上 user の terminal decision は agent hold を経た
候補にしか出せないため、画面で選んだ行為は候補の `action` として運ばれ、判断そのものは後段で行う。

```
コンソールの選択 → staged decisions → build_change_requests_from_review_inbox.py
  ├→ review_console_change_request レポート → build_event_inbox_candidates.py → 候補（event_update）→ J0-read → 裁定 → E2a以降で反映
  └→ rdb_change_requests.json（dry_run_only）→ 人の昇格 → apply_change_requests（旧経路・当面は残す）
```

### 日次で積んでいるのは、いくつの入口か

1番の「積む」を、日次の `collect.yml` が実際にどう動かしているかを書いておく。
ここが長らく仕様に書かれておらず、**毎日動いているのに触っても逆引きに出てこない状態だった**
（2026-08-14に配分。それまで `collect.yml` が呼ぶ38本のうち23本がどの仕様にも属していなかった）。

積む入口は5つのレーンに分かれていて、それぞれ独立に有効・無効を切り替えられる。
**スクリプト側の既定はどれも off** で、動かすにはリポジトリ変数のガードと確認句の両方が要る
（たとえば `--confirm 'RUN SCHEDULED YOUTUBE AGGREGATE DUAL WRITE'` のような句を workflow が渡す）。
`83bf7d0` 時点で有効なのは稀少シグナル・YouTube集約・低優先の3つで、
`REVIEW_INBOX_YOUTUBE_ACTIVE_DUAL_WRITE_ENABLED` だけ `false` のままである。
既定を off にしてあるのは、新しい積み方を本番へ繋いだ瞬間に全件が静かに流れ込むのを防ぐためで、
**入口の量が人の処理量を超えることがこの工程の最大の失敗だから**である。

| レーン | 積む前に作るもの | 受信箱へ流す実行 |
|---|---|---|
| X候補の日次コホート | `x_candidate_backlog.py merge` → `x_gap_adapter.py --backlog ... --daily-limit 5` | `run_review_inbox_x_gap_scheduled.py`（`REVIEW_INBOX_X_GAP_DUAL_WRITE_ENABLED`） |
| 稀少シグナル | `build_rare_signal_backcheck_queue.py` → `export_rare_signal_backcheck_reviews.py` → `stage_rare_signal_backcheck_reviews.py` | `run_review_inbox_rare_signal_scheduled.py` |
| YouTube集約 | [YouTube取り込み](09-youtube.md)側で用意 | `run_review_inbox_youtube_scheduled.py`（同じくあちら） |
| 低優先 | `build_missing_venue_review_from_song_associations.py`（会場側）、`build_historical_reference_quality_review.py` | `run_review_inbox_low_priority_scheduled.py` |
| X由来 | `build_x_gap_candidates.py`（収集側）→ `review_inbox_adapters/x_gap_adapter.py` → `build_x_review_lanes.py` | 定期の二重書き込みは持たず、整形したJSONを置くところで止まる |

YouTube曲証拠のLLM判断は、現行DB行の内容指紋まで一致したときだけ画面上の判断済みにする。
入力ファイルは実行時のDBより古いことがあるため、低優先キューのような「現在集合から消えた」だけの自動解決はしない
（INV-RVW-019）。

X由来だけ形が違う。`build_x_review_lanes.py` は穴の候補を**3つの運用レーンへ切り分ける**のが役目で、
1番目のレーンは意図的に厳しくしてある（登録済みの公式ソースだけを通す）。
機械が拾った穴をそのまま人へ渡すと、レビュー待ちが人の処理速度を超えて詰まるためである。

このほかに、日次で回っている周辺の入口が3種類ある。

- **おと向けのニュース要約** — `build_x_news_digest_for_oto.py` が、収集済みの投稿から要約を作る
  （X・Notion・LLMのいずれも呼ばない）。おとが読んで裁定した結果は
  `promote_x_news_digest_reviews.py` が稀少シグナル候補へ昇格させる。
  機械が用意した要約を最終解釈として信用しない、という前提でこの2段になっている。
- **収穫（harvest）** — `build_retrospective_harvest.py` と `build_weekly_harvest_candidates.py --days 3`、
  `prepare_weekly_harvest_review.py` が、用語候補と曲・会場の共起をレビュー用のキューにする。
  名前は「週次」だが**日次で動いている**ので、名前から実行間隔を推測しないこと。
  低優先の完全スナップショットは、人/LLMの凍結判断overlayと内容の指紋が一致する行を現在のpending集合から除く
  （INV-RVW-019）。これは判断の投影だけで、正本factへの適用ではない。
- **掲示物のOCR** — `build_event_poster_ocr_queue.py` が、チラシ・貼り紙の写真が付いた投稿を
  優先度の高いOCRの列にする。曲目表のOCR（`build_song_ocr_queue.py`）は[曲目](08-songs.md)側の別経路である。

`build_x_account_console.py` は積む入口ではなく、**読んでいる相手を人が見られるようにする画面**を作る。
2026-07-26まで「誰を読んでいるのか」を見る手立てが無かったために作られたもので、
`review_x_candidate_posts.py` はその候補アカウントを直近の投稿から人が判断するための補助である。

日次とは別に、**公式ソースURLのレビュー列**を作る `build_official_source_review.py` が
`refresh_official_source_review.yml` から動く。毎年開かれる行事の公式URLが古くなっていないかを人が見るための列で、
公開面で出典を示せるかどうかに直結する（出典を出してよい情報源の線引きは運用側の判断である）。
同じworkflowの区公式registry巡回は、発見したページを `WardOfficialSourceAdapter` で
`source_id=ward_official_source` の受信箱snapshotへ変換する。legacy公式URL候補とlineageを混ぜず、
adapterはcanonical DBへ書かない。人のレビュー後の適用境界は従来の公式ソース経路と同じである。

受信箱のスキーマ移行は `review_inbox_migration_runner.py` が `migrate_review_inbox_v2.yml` から実行する。
**移行の入口をここに1本だけ置いてあるのは、日常の書き込み経路が副作用でスキーマを変えないようにするため**で、
その約束が INV-RVW-003 である。この runner はマスタDBを publish しない作りになっていて、
移行とS3への公開を必ず別の操作に保っている。

## 依存と影響

**上流**: 各収集・判断工程。積まれる項目の質が悪いと、人の時間が浪費される。
受信箱に積む基準が緩すぎると、**詰まりの原因そのものになる**。

**下流**: [マスタ](04-master.md)。ここでの裁定がRDBの確定情報になる。

## 壊れたときの症状

| 症状 | まず見る場所 |
|---|---|
| レビュー待ちが減らない・増え続ける | 積む基準が緩すぎないか。人の処理速度と釣り合っているか |
| 裁定したのに反映されない | 昇格（INV-RVW-004）を実行したか |
| 1回の裁定が2件になっている | INV-RVW-001 |
| 見覚えのないイベントが変わっている | INV-RVW-002 |

## 未解決・注意点

- **受信箱に積む選別基準の作り直しが未着手。** いまは積まれる量が人の処理量を上回りうる。
  律速工程に対して入口を絞らないままなので、根本的にはここが宿題になっている。
- ~~レビューコンソールの「次に何をすべきか」の提示が弱く、優先順位が人の記憶に依存している。~~
  **2026-08-17に次アクション別表示、未来情報の先頭表示、完全な現在集合から消えた残骸の表示上の自動解決を実装した。**
  ただしYouTube入力は実行時だけ生成されるため、リポジトリ内で完全性を再現できず、この自動解決の対象外である。
- ~~アダプタが種類ごとに増える構造なので、共通の契約（L2）を切り出したい。~~
  **2026-08-14に[受信箱アダプタの契約](../L2/review-inbox-adapter.md)として切り出した。**
  ただし切り出したのは共通部分（項目の形・禁止事項・突き合わせ）だけで、
  種類ごとの `payload` の中身は各アダプタの実装にしか書かれていない。

---

こと（Claude Code）
