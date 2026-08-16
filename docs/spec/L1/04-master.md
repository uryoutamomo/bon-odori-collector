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
  - master_db_s3_artifact.py
  - audit_master_rdb.py
  - master_rdb_freeze_policy.py
  - transition_ended_occurrences.py
  - run_event_state_axes_migration.py
  - run_post_batch_maintenance.py
  - run_x_song_identity_migration.py
depends_on:
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
verified_by:
  - tests/test_apply_change_requests.py
  - tests/test_master_db_s3_artifact.py
  - tests/test_audit_master_rdb.py
  - tests/test_e2_identity_judgment.py
  - tests/test_x_song_identity_migration.py
  - tests/test_x_song_apply_safety.py
  - tests/test_x_song_materialization_lifecycle.py
updated_for: 64c874f
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
- **なぜ**: commit後の監査では失敗を検出しても正本を元へ戻せず、根拠と公開factが半端な状態になる。
- **破れたときの症状**: writerが失敗を報告したのに正本だけ変更済み、または既存curated曲のsong ID/titleが変わる。
- **守っているコード**: `report_apply/x_song_apply_safety.py`、
  `report_apply/materialize_x_song_resolutions.py`、`report_apply/retract_x_song_materializations.py`、
  `report_apply/event_report_helpers.py::link_resolved_occurrence_song`
- **守っているテスト**: `tests/test_x_song_apply_safety.py`、
  `tests/test_x_song_materialization_lifecycle.py::test_resolved_helper_fails_closed_on_existing_fact_collision`

## 主要な流れ

日次では、S3から取得 → 監査 → 各種同期 → 変更があれば publish、という順に進む。

1. **取得** — `master_db_s3_artifact.py fetch --overwrite`。チェックサム検証つき（INV-MST-006）。
2. **監査** — `audit_master_rdb.py`。取得直後に一度、書き込み後にもう一度走る。
3. **状態軸の同期** — `event_model/state_axes_migration.py` 系。開催回の状態を正規化する。
   日次の実行入口は `run_event_state_axes_migration.py` で、**既定は dry-run**、
   実際に書くには `--execute` が要る（INV-MST-003と同じ作法）。
   `vars.EVENT_STATE_AXES_ENABLED` が `true` のときだけ動き、書き込む前に
   マニフェストのチェックサムを控えてCASの比較対象にする（INV-MST-004）。
4. **終了した開催回の遷移** — `transition_ended_occurrences.py`。過ぎた開催回を「終了」へ落とす。
   これが動かないと、終わった行事が公開面に「開催予定」として残る。
5. **変更リクエストの適用** — `report_apply/apply_change_requests.py`。dry-run → レビュー → apply → 再検証（INV-MST-003）。
6. **publish** — 書き込みが起きたときだけ。CAS（INV-MST-004）とスキーマ退行検査（INV-MST-005）を通る。

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
- 予測日（`predicted_occurrence_dates`）は14件と少なく、器はあるが実質的に使われていない。

---

こと（Claude Code）
