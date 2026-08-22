---
id: L1-master
layer: L1
title: マスタ（Master RDB）サブシステム
owns:
  - master_rdb/__init__.py
  - master_rdb/audit.py
  - master_rdb/freeze_policy.py
  - master_rdb/s3_artifact.py
  - master_rdb/unified_model_audit.py
  - rdb_builders/**
  - report_apply/**
  - event_model/**
  - data/llm_event_date_prediction_judgments.json
  - docs/llm-event-date-certainty-policy.md
  - master_db_s3_artifact.py
  - audit_master_rdb.py
  - data/official_notice_reports/detail_cleanup_repair_20260816.json
  - master_rdb_freeze_policy.py
  - transition_ended_occurrences.py
  - run_event_state_axes_migration.py
  - sync_event_date_predictions_rdb.py
  - run_post_batch_maintenance.py
  - run_x_song_identity_migration.py
  - promotion_candidates/build_historical_promotion_candidates.py
  - scripts/verify_review_backlog_application.py
  - .github/workflows/apply-reviewed-change-requests.yml
depends_on:
  - L1-collection
  - L1-platform
invariants:
  - INV-MST-001
  - INV-MST-002
  - INV-MST-003
  - INV-MST-004
  - INV-MST-005
  - INV-MST-006
  - INV-MST-007
  - INV-MST-008
  - INV-MST-009
  - INV-MST-010
  - INV-MST-011
  - INV-MST-012
  - INV-MST-013
  - INV-MST-014
verified_by:
  - tests/test_apply_change_requests.py
  - tests/test_master_db_s3_artifact.py
  - tests/test_audit_master_rdb.py
  - tests/test_e2_identity_judgment.py
  - tests/test_x_song_identity_migration.py
  - tests/test_x_song_apply_safety.py
  - tests/test_x_song_materialization_lifecycle.py
  - tests/test_event_date_prediction_judgment.py
  - tests/test_build_historical_promotion_candidates.py
  - tests/test_reviewed_change_requests_workflow.py
  - tests/test_sync_event_date_predictions_rdb.py
  - tests/test_collect_event_state_axes_wiring.py
updated_for: b5e6c0a
---

# マスタ（Master RDB）サブシステム

> 上位は[全体地図](../README.md)。下流は[公開サブシステム](05-publication.md)。書き方の決まりは [SPEC-GUIDE](../SPEC-GUIDE.md)。

## この工程は何のためにあるか

「確定した事実」の正本を持つ工程である。イベント系列、開催回、会場、曲目、そして
それぞれの根拠が SQLite（`data/bon_odori_master.sqlite`）に入っていて、公開もメールもここから作られる。

この工程の難しさは、保存することではなく **確定と推測を混ぜないこと**にある。
盆踊りは毎年ほぼ同じ時期・同じ場所で開かれるので、「去年8月第2土曜だったから今年もそうだろう」は
だいたい当たる。だが当たることと確定していることは違う。過去実績をそのまま今年の開催日として
書き込んでしまえば、RDBは「確定情報」の顔をしたまま推測を抱え込み、下流のどこにもそれを見分ける手段が無くなる。

したがってこの工程の設計は、**書き込み口を絞ることに集中している。**
何でも書ける汎用の更新機能をあえて持たず、変更の種類を有限にし、種類ごとに必要な根拠を強制する。

## 入力と出力

**入力**

| 何を | どこから |
|---|---|
| 変更リクエスト（有限種別のJSON） | レビュー工程・現地レポート・掲示物レポート |
| 過去実績・YouTube由来の観測 | 収集/判断工程 |
| S3上の最新DB成果物 | `MASTER_DB_S3_BUCKET` / `MASTER_DB_S3_PREFIX` |

**出力**

| 何を | どこへ |
|---|---|
| 正本DB | `data/bon_odori_master.sqlite`（`6537e7f` 時点で系列347・開催回364・根拠31,329件） |
| DB成果物とマニフェスト | S3（`latest` と スナップショット） |
| 監査結果 | `audit_master_rdb.py` の出力 |
| dry-run結果 | `data/change_requests_apply_dry_run.sqlite` |

## 不変条件

### INV-MST-001 RDBへの反映は有限の変更種別だけを通す

- **内容**: `report_apply/apply_change_requests.py` が受け付ける変更は
  `create_current_year_occurrence` / `confirm_current_year_date` / `add_historical_reference` /
  `update_venue` / `add_song_evidence` に限られる（`CHANGE_TYPES`）。
  未知の種別は検証で弾かれ、自由記述のパッチは受け付けない。
- **なぜ**: 「何でも書ける口」を1つ用意すると、種別ごとに必要な根拠を強制できなくなるから。
  種別を絞ることで、たとえば「今年の開催日を確定する」には今年のソースが要る、という規則を機械が守れる。
- **破れたときの症状**: 根拠のない値がRDBへ入り、どの情報が確定でどれが推測か区別できなくなる。
  イベント個別の `apply_*.py` が増殖し、それぞれ違う検証をするようになる。
- **守っているコード**: `report_apply/apply_change_requests.py` の `CHANGE_TYPES` と検証処理
- **守っているテスト**: `tests/test_apply_change_requests.py::test_applies_four_finite_change_types`

### INV-MST-002 今年の開催日の確定には、今年のソースを要求する

- **内容**: `confirm_current_year_date` は、根拠の種別が
  `official_current_year` / `organizer_current_year` / `trusted_x_current_year` の
  いずれかでなければ検証で落ちる（`CURRENT_YEAR_SOURCE_KINDS`）。
- **なぜ**: **これがこの仕組みの一番大事な約束である。** 過去年のYouTube動画や去年の開催実績は、
  「例年この時期」というヒントにはなるが、今年開かれる証拠にはならない。
  過去実績だけで開催日を確定できてしまうと、中止になった盆踊りへ人を歩かせることになる。
- **破れたときの症状**: 実際には開催されない日程が「確定」として公開される。
  一度確定として入ると、下流からは推測だったことが分からない。
- **守っているコード**: `report_apply/apply_change_requests.py` の `CURRENT_YEAR_SOURCE_KINDS` と
  `apply_confirm_current_year_date()`
- **守っているテスト**: `tests/test_apply_change_requests.py::test_validates_current_year_confirmation_requires_current_year_source`

### INV-MST-003 既定は dry-run。実DBへの書き込みには確認句が要る

- **内容**: `apply_change_requests.py` は既定でコピーDB（`data/change_requests_apply_dry_run.sqlite`）にだけ書く。
  実DBへ反映するには `--apply` と、`manual_apply_guards.CHANGE_REQUESTS_CONFIRMATION` の確認句が要る。
  さらに `dry_run_only` が付いたリクエストが1件でも含まれていれば、`--apply` を拒否する。
- **なぜ**: RDBは公開・メール・レビューすべての土台なので、壊れたときの影響範囲が最も広い。
  「試すつもりが本番に入った」を構造的に起こせなくしてある。
- **破れたときの症状**: 検証目的の実行が本番RDBを書き換える。
- **守っているコード**: `report_apply/apply_change_requests.py` の `main()` と `require_confirmation()` 呼び出し
- **守っているテスト**: `tests/test_apply_change_requests.py::test_apply_refuses_dry_run_only_requests`

### INV-MST-004 S3の latest を上書きするときは、期待するチェックサムと一致させる

- **内容**: `master_db_s3_artifact.py` の publish は、リモートに manifest が既にある場合、
  `--expect-remote-checksum` が実際のリモート値と一致しない限り `SystemExit` で止まる。
  一致確認を省くには `--force` が要る。
- **なぜ**: DBは複数の実行主体（日次workflow・手元の適用・おとの作業）が触る。
  取得してから publish するまでの間に別の実行が新しい成果を上げていた場合、
  素直に上書きすると**他人の書き込みが黙って消える**。いわゆる compare-and-swap をここで担保している。
- **破れたときの症状**: 反映したはずの変更が次の日には消えている。誰の作業が消えたのか追跡できない。
- **守っているコード**: `master_rdb/s3_artifact.py` の publish 経路（`--expect-remote-checksum` の照合）
- **守っているテスト**: `tests/test_master_db_s3_artifact.py::test_publish_cas_requires_matching_checksum_before_any_upload`、`tests/test_master_db_s3_artifact.py::test_publish_cas_requires_expectation_unless_forced`、`tests/test_master_db_s3_artifact.py::test_publish_cas_accepts_match_and_force_override`

### INV-MST-005 スキーマが退行したDBで latest を上書きしない

- **内容**: publish 前に `enforce_inbox_schema_not_downgraded()` が、ローカルの review inbox スキーマ版が
  リモートより古い場合に publish 自体を止める。意図的な巻き戻しには `--force` が要る。
  リモート manifest にキーが無い移行期の場合は、通したうえでその旨を出力に残す。
- **なぜ**: **2026-07-24 に実際に起きた事故の再発防止である。** v1系統のDBが本番を上書きし、
  v2を要求する dual-write が5日間毎日失敗し続けた。CASはチェックサムしか見ないので、
  「新しいが中身が古い」DBを止められなかった。
- **破れたときの症状**: publish は成功するのに、翌日から下流の定期処理が毎日失敗する。
  しかも失敗しているのが別の工程なので、原因がここだと気づくまで時間がかかる。
- **守っているコード**: `master_rdb/s3_artifact.py` の `enforce_inbox_schema_not_downgraded()`
- **守っているテスト**: `tests/test_master_db_s3_artifact.py::test_publish_blocks_inbox_schema_downgrade`、
  `tests/test_master_db_s3_artifact.py::test_force_allows_intentional_inbox_schema_downgrade`

### INV-MST-006 取得したDBは、必ずチェックサムを検証してから使う

- **内容**: `fetch` はリモート manifest の `database_checksum` を必須とし、
  ダウンロードしたファイルのハッシュが一致しなければ `SystemExit` で止まる。
  検証に通ったものだけを `atomic_replace()` で所定の位置へ置く。
- **なぜ**: 壊れたDBや途中までのDBで日次パイプラインが走ると、
  「データが少ないだけ」に見えて全工程が静かに劣化する。
- **破れたときの症状**: 公開件数が理由なく減る。監査だけが異常を示す。
- **守っているコード**: `master_rdb/s3_artifact.py` の `verify_checksum()` と fetch 経路
- **守っているテスト**: `tests/test_master_db_s3_artifact.py::test_fetch_verifies_checksum_and_writes_local_manifest`

### INV-MST-007 会場は正規化名と住所の完全一致でのみ再利用する

- **内容**: `ensure_venue()` は正規化名と住所が完全一致する会場だけを再利用し、似た名称を自動で束ねない。
- **なぜ**: 部分一致は別の物理会場を同じ会場として結びつける。2026-08-07には「さくら公園」が「東葛西さくら公園」へ誤照合した。
- **破れたときの症状**: 別会場の行事が一つの会場にまとめて表示され、会場・日程の根拠が混ざる。
- **守っているコード**: `report_apply/event_report_helpers.py` の `ensure_venue()`
- **守っているテスト**: `tests/test_firsthand_report_helpers.py::FirsthandReportHelpersTest::test_ensure_venue_creates_instead_of_absorbing_a_similar_name`

### INV-MST-008 新しい系列の作成は追加だけで、既存を黙って再利用しない

- **内容**: `create_event_series` は系列・開催回・日付を新規に作るだけで、既存行を更新しない。正規化した系列キーが既にあれば `series_key_already_exists` で止める（その場合は `create_current_year_occurrence` を使う）。`series_id` を同梱した要求は受け付けない。あわせて会場は `venue_id` で指せるようになり、IDが渡されたときは `ensure_venue()` を経由しない。
- **なぜ**: 従来の `register_new` は実体が `ensure_series_and_occurrence()` で、同じ正規化名の系列を黙って再利用し、同じ年の開催回があれば `ON CONFLICT ... DO UPDATE` で会場と日付を上書きしていた。「新規追加」のつもりの操作が、別の行事の確定日を書き換えうる。会場も名前でしか渡せず、表記が少し違うだけで同じ場所が二重に登録された（2026-08-07 鹿骨中学校）。
- **破れたときの症状**: 新規登録したはずが既存の開催回の日付・会場が変わる。同じ会場が2行に増える。
- **守っているコード**: `report_apply/apply_change_requests.py` の `apply_create_event_series()` と `_resolve_venue()`
- **守っているテスト**: `tests/test_e2_identity_judgment.py::test_create_event_series_never_touches_an_existing_series`、`tests/test_e2_identity_judgment.py::test_duplicate_series_key_is_refused`、`tests/test_e2_identity_judgment.py::test_update_venue_by_id_creates_no_venue_row`

### INV-MST-009 確からしさは、理由なしに下がらない

- **内容**: `confirm_occurrence_schedule_venue()` は、呼び出し側が `confidence` を名指ししていないとき（`confidence_is_explicit=False`）は既存値を下げない。順位は `unknown < medium < high < confirmed` で、順位表に無い値（`superseded` など）は既定値では触らない。**名指ししたときは下げる指定もそのまま通す。**
- **なぜ**: 下げること自体は正しい場合がある——根拠が覆った、疑わしいと分かった、といったときに下げられないほうが困る。禁じるべきなのは「呼び出し側が何も言っていないのに、既定値が既存を書き換える」ことだけである。実データは confirmed 253 / unknown 59 / high 49 で、既定の `"high"` が確定済みの開催回を上書きすると理由のない格下げになる。2026-08-15 の E2 実地試行では、適用した9件すべてで `confirmed → high` が起きた。
- **破れたときの症状**: 情報を足すほど確からしさが下がる（既定値を守れていない場合）。あるいは、根拠が覆っても確からしさを下げられない（名指しを通していない場合）。
- **守っているコード**: `report_apply/event_report_helpers.py` の `_kept_confidence()` と `confidence_is_explicit`
- **守っているテスト**: `tests/test_e2_identity_judgment.py::test_confirmed_is_not_downgraded_by_the_default`、`tests/test_e2_identity_judgment.py::test_an_explicit_lower_confidence_is_applied`、`tests/test_e2_identity_judgment.py::test_a_value_outside_the_rank_table_is_left_alone_by_the_default`

### INV-MST-010 X曲factのwriterはpreflight・backup・commit前検証を省略しない

- **内容**: X曲のschema migration、decision apply、materializer、retractorはdry-runを既定にし、実行時は
  同一入力をDB複製へpreflightしてからbackupを作る。実DBではtransactionを開いたまま
  `integrity_check` / `foreign_key_check` を行い、通過後だけcommitする。既存factとのidentity衝突は上書きせずrollbackする。
  ただし同一factに限り、旧経路が残した `song_id=NULL` はCAS的にsong IDだけ補完でき、他列は変更しない。
- **なぜ**: commit後の監査では失敗を検出しても正本を元へ戻せず、根拠と公開factが半端な状態になる。
- **破れたときの症状**: writerが失敗を報告したのに正本だけ変更済み、または既存curated曲のsong ID/titleが変わる。
  NULL補完でorigin・生タイトル・確からしさまで更新される、または別song IDのfactへ根拠を混ぜる。
- **守っているコード**: `report_apply/x_song_apply_safety.py`、
  `report_apply/materialize_x_song_resolutions.py`、`report_apply/retract_x_song_materializations.py`、
  `report_apply/event_report_helpers.py::link_resolved_occurrence_song`
- **守っているテスト**: `tests/test_x_song_apply_safety.py`、
  `tests/test_x_song_materialization_lifecycle.py::test_resolved_helper_fails_closed_on_existing_fact_collision`、
  `tests/test_x_song_null_song_id_linking.py`

### INV-MST-011 LLM日付予測は開催有無と日付一致を1つの確度として裁定し、機械検査を省略しない

- **内容**: LLMの `joint_probability` は「同一イベントが対象年に開催され、かつ予測日範囲と一致する確率」とする。
  Pythonは有限カレンダー規則から対象年と根拠年の日付を再計算し、凍結ID・名称・会場・対象年・出典URL・競合・
  根拠別の確率上限を検査する。90%以上は `ほぼ確実` だが、対象年の公式直接証拠が無い限り
  `predicted × rule_predicted` から `confirmed` へ上げない。適用先は元DBと異なるSQLiteコピーに限定する。
- **なぜ**: 従来のPythonスコアは過去年の日付配列しか読めず、主催者の明示規則や当年の地域情報を評価できない。
  一方でLLMの自由な確率だけを受け入れると、系列違い・カレンダー計算違い・根拠不足が高確度表示になる。
  意味判断をLLM、有限条件と書き込み境界を機械に分ける必要がある。
- **破れたときの症状**: 強い根拠がある予測が `medium` のまま落ちる。逆に過去年1件だけの候補が
  `ほぼ確実` と表示される。予測日が確定日としてRDBへ混入する。
- **守っているコード**: `event_model/event_date_prediction_judgment.py`
- **守っているテスト**: `tests/test_event_date_prediction_judgment.py`

### INV-MST-012 レビュー済み曲根拠は派生値まで確定してから正本DBを公開する

- **内容**: `apply-reviewed-change-requests.yml` はレビュー済み変更要求をコピーDBへdry-runした後、
  正本候補へ適用する。`add_song_evidence` が含まれる場合は対象開催回の曲確率を再計算し、
  過去実績からの日付候補を再構築し、RDBだけを入力にした公開JSON出力と適用内容の検証を通す。
  その同じSQLite成果物だけをCASでS3へpublishし、再取得後にも適用検証と公開JSON出力を繰り返す。
- **なぜ**: 曲根拠だけを書いて確率を古いまま残す、または公開JSONの旧フォールバックだけで見た目を直すと、
  次の正本同期で表示が戻る。日付候補の照合が短い正式名を取りこぼすと、RDBが正しくても公開出力が失敗する。
- **破れたときの症状**: RDBには根拠があるのに曲の確率が空または更新前のままになる。
  公開JSONの再生成で曲目が消える、あるいは無関係なJSONフォールバックなしでは書き出せない。
- **守っているコード**: `.github/workflows/apply-reviewed-change-requests.yml`、
  `promotion_candidates/build_historical_promotion_candidates.py`、
  `scripts/verify_review_backlog_application.py`
- **守っているテスト**: `tests/test_reviewed_change_requests_workflow.py::test_workflow_dry_runs_before_apply_and_verifies_every_stage`、
  `tests/test_build_historical_promotion_candidates.py::BuildHistoricalPromotionCandidatesTest::test_exact_event_and_venue_match_short_canonical_name`

### INV-MST-013 生成された日付予測は正本RDBへ先に同期し、曖昧な系列へは書かない

- **内容**: `sync_event_date_predictions_rdb.py` は `data/event_date_predictions.json` の対象年予測を、
  系列の正式名・別名と会場の正式名・別名の組で一意に解決してから
  `predicted_occurrence_dates` へ同期する。限定的な名称包含を許す場合も会場一致と系列一意性を必須とし、
  0件または複数系列、または過去年の根拠が2年未満なら全体を停止する。同期対象は
  `source='event_date_predictions'` の行と、外部キーに必要な最小の履歴候補行の不足分だけで、
  既存の履歴候補、手動・LLM由来の予測、`event_occurrences` の確定日は変更・削除しない。既定はDBコピーへのdry-runで、
  executeも同じコピーpreflight、完全性検査、確認句を通す。日次はこの同期を公開射影より前に実行し、
  CAS publish後の再取得DBが変更0であることを `--check` する。
- **なぜ**: 2026-08-17・18はYouTube日次がJSON予測を13件から17件へ増やした一方、
  RDBが13件のまま残ったため、INV-PUB-006が日次収集を2日連続で停止した。
  ガードを緩めると二重正本へ戻るので、生成物から正本への狭い同期口を復旧する。
  一方、既存の履歴候補一括再構築を日次化すると、予測以外の派生表まで自動更新して範囲が広すぎる。
- **破れたときの症状**: YouTube日次は成功するのに、次の `collect.yml` が
  `public date prediction JSON fallback is forbidden` でcollector実行前に停止する。
  または同名・類似名の別系列へ予測が付き、予測が開催確定日へ混入する。
- **守っているコード**: `sync_event_date_predictions_rdb.py`、`.github/workflows/collect.yml` の
  `Sync date predictions and canonical event-state axes to master RDB` ステップ
- **守っているテスト**: `tests/test_sync_event_date_predictions_rdb.py`、
  `tests/test_collect_event_state_axes_wiring.py::CollectEventStateAxesWiringTest::test_prediction_sync_does_not_depend_on_the_state_axes_feature_flag`

### INV-MST-014 開催日根拠の追加で公開用の代表出典を格下げしない

- **内容**: `confirm_current_year_date` は新しいURLを `evidence_items` と開催回への根拠リンクへ必ず保存する。
  ただし単数の `event_occurrences.source_url` は公開用の代表出典として扱い、通常のWebページ、
  公式・主催者X、未登録SNSの順で品質を比較する。新しいURLの品質が明確に上がる場合だけ差し替え、
  同等以下なら既存URLを残す。
- **なぜ**: `source_url` を無条件に上書きすると、公式ページが私人や第三者のX投稿へ置き換わり、
  公開exportが元の公式URLを復元できない。新しい根拠を記録することと、公開する代表出典を選ぶことは別である。
- **破れたときの症状**: 開催日を追加確認した後、公開ページの「公式告知あり」が消える、
  または公式サイトへのリンクがSNS投稿へ置き換わる。
- **守っているコード**: `report_apply/apply_change_requests.py` の
  `_preferred_representative_source()` と `apply_confirm_current_year_date()`
- **守っているテスト**: `tests/test_apply_change_requests.py::ApplyChangeRequestsTests::test_confirm_current_year_date_does_not_replace_web_source_with_social_post`、
  `tests/test_apply_change_requests.py::ApplyChangeRequestsTests::test_confirm_current_year_date_replaces_social_source_with_web_source`

## 主要な流れ

日次では、S3から取得 → 監査 → 各種同期 → 変更があれば publish、という順に進む。

1. **取得** — `master_db_s3_artifact.py fetch --overwrite`。チェックサム検証つき（INV-MST-006）。
2. **監査** — `audit_master_rdb.py`。取得直後に一度、書き込み後にもう一度走る。
3. **生成予測の同期** — `sync_event_date_predictions_rdb.py`。JSON生成物と
   `predicted_occurrence_dates` の差をDBコピーでpreflightし、`event_date_predictions` 所有行だけを同期する。
   状態軸のfeature flagが無効でもこの同期は止めない（INV-MST-013）。
4. **状態軸の同期** — `event_model/state_axes_migration.py` 系。開催回の状態を正規化する。
   日次の実行入口は `run_event_state_axes_migration.py` で、**既定は dry-run**、
   実際に書くには `--execute` が要る（INV-MST-003と同じ作法）。
   `vars.EVENT_STATE_AXES_ENABLED` が `true` のときだけ動き、書き込む前に
   マニフェストのチェックサムを控えてCASの比較対象にする（INV-MST-004）。
5. **終了した開催回の遷移** — `transition_ended_occurrences.py`。過ぎた開催回を「終了」へ落とす。
   これが動かないと、終わった行事が公開面に「開催予定」として残る。
6. **変更リクエストの適用** — `report_apply/apply_change_requests.py`。dry-run → レビュー → apply → 再検証（INV-MST-003）。
   曲根拠を足した場合は、確率較正 → 過去実績の日付候補再構築 → 公開JSON検証まで同じDBで終える（INV-MST-012）。
7. **publish** — 書き込みが起きたときだけ。生成予測と状態軸は同じSQLite成果物を1回だけpublishし、
   CAS（INV-MST-004）とスキーマ退行検査（INV-MST-005）を通る。

**通知レポートの再適用**では、`report_apply/apply_official_notice_report.py` が同じ通知の
evidence link を開催回にすでに持つ場合、`detail_addendum` と `detail_replacement` を再実行しない。
後から人が整えた公開本文を古い通知が戻してしまうことを防ぐためである。一方で、日付・会場・
evidence・曲の冪等な適用は続ける。別の通知evidenceによる後続の本文差替は正しく反映され、
古い通知を再実行しても上書きされない。

2026-08-16 の14件公開detail修復は完了済みで、修復台帳は監査記録として保持する。実行証跡は GitHub Actions run 31958734256 の artifact にある。

日次のほかに、**バッチの後始末を読むだけのレポート**がある。`run_post_batch_maintenance.py` は
RDBとローカルのJSON出力を読み、件数と気になる点をまとめたJSON/Markdownを出す。書き込みはしない。
呼んでいるのは[YouTube取り込み](09-youtube.md)の日次workflowだけだが、
中身はRDB全体の点検なのでこの仕様の持ち物にしてある。

**凍結という仕組みもある。** `master_rdb_freeze_policy.py` は、移行中の生成物を一時的に止めるための
スイッチで、日次workflowが `is-frozen <group>` の終了コードで分岐している。
凍結されたグループの生成物は作られないので、「出力が消えた」と思ったらまずここを疑う。

## 依存と影響

**上流**: 実行基盤（[L1-platform](07-platform.md)）。S3認証とworkflowの実行順に依存する。
取得に失敗したのに後続が走ると、古いDBを正本として扱ってしまう。

**下流**: [公開サブシステム](05-publication.md)、メール配信、レビュー工程。
特に公開はRDBの素直な射影ではなく後処理が重なるため、**RDBを直しても公開が変わらないことがある**。
公開側の不具合を調べるとき、RDBが正しいことは十分条件にならない。

## 壊れたときの症状

| 症状 | まず見る場所 |
|---|---|
| 反映したはずの変更が消えている | INV-MST-004。別の実行と競合していないか |
| publish後、翌日から別の工程が毎日失敗する | INV-MST-005。スキーマ退行 |
| 終わった行事が「開催予定」のまま | `transition_ended_occurrences.py` が走ったか |
| ある生成物が丸ごと出ていない | 凍結ポリシー（`master_rdb_freeze_policy.py`）を確認 |
| 手で直したはずの値が元に戻る | 再取り込みで上書きされている。生成元を直す必要がある |

最後の行は繰り返し起きている問題である。**RDBを直接UPDATEしても、生成元を直さない限り再取り込みで戻る。**
直すべきは値ではなく、その値を作っている工程のほうであることが多い。

## 未解決・注意点

- テーブルのスキーマそのものは[マスタRDBスキーマ契約](../L2/master-schema.md)に書いた
  （`event_series` と `event_occurrences` の関係、`evidence_items` の使われ方はそちらを見る）。
- `report_apply` には既知のバグが残っている領域がある（詳細は別途）。
- 予測日（`predicted_occurrence_dates`）は公開射影で使われる正本である。生成予測の件数が増えたときは
  INV-MST-013の同期レポートと、再取得後の変更0チェックを確認する。

---

おと（Codex）
