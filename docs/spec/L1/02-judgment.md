---
id: L1-judgment
layer: L1
title: 自動判断サブシステム
owns:
  - build_x_extraction_packets.py
  - apply_x_extraction_results.py
  - collection_support/event_evidence.py
  - collection_support/suppression_rules.py
  - collection_support/tokyo23_scope.py
  - collection_support/x_source_officiality.py
depends_on:
  - L1-collection
invariants:
  - INV-JDG-001
  - INV-JDG-002
  - INV-XPE-001
  - INV-XPE-002
  - INV-XPE-003
  - INV-XPE-004
  - INV-XPE-005
  - INV-XPE-006
  - INV-XPE-007
  - INV-XPE-008
  - INV-XPE-009
  - INV-XPE-010
  - INV-XPE-011
  - INV-XPE-012
  - INV-XPE-013
  - INV-XPE-014
  - INV-XPE-015
  - INV-XPE-016
verified_by:
  - tests/test_event_evidence.py
  - tests/test_x_post_extraction_e0x.py
  - tests/test_x_post_extraction_songs.py
updated_for: 7bcacd0
---

# 自動判断サブシステム

> 上位は[全体地図](../README.md)。これは自動採用器ではなく、観測を説明可能な優先候補へ整える工程である。

## この工程は何のためにあるか

収集された文章から日付・場所・イベント名などの根拠を取り出し、人が確認すべき候補を優先付けする。弱い断片を消して「なかったこと」にするより、弱い理由を残して人が判断できるようにする。

## 入力と出力

入力は収集済みの投稿と除外語・地理・公式性の設定。出力はイベント候補の本文、根拠、スコア、推定日付・会場・関連キーに加え、E0X回答から作る曲名観測 `data/x_song_observations.json` と界隈語観測 `data/x_glossary_observations.json` である。観測台帳は候補を失わないための中間出力であり、曲マスタ、開催回、用語集runtimeへはまだ接続しない。

## 不変条件

### INV-JDG-001 判定には盆踊り文脈と説明可能な採点理由を残す

- **内容**: `classify_event_evidence()` はA〜Eのパターン、日付・場所等の根拠からスコアと `score_reasons` を作り、盆踊り文脈が弱ければ減点する。
- **なぜ**: 点数だけでは人が誤判定を発見できず、一般的な夏祭り情報を盆踊り候補として増幅してしまうから。
- **破れたときの症状**: 根拠のない高優先候補が増え、レビュー担当者が採否の理由を追えない。
- **守っているコード**: `collection_support/event_evidence.py` の `classify_event_evidence()`
- **守っているテスト**: `tests/test_event_evidence.py::test_classifies_patterns_and_explainable_score`

### INV-JDG-002 一般名詞・断片をイベント名として確定候補にしない

- **内容**: イベント名らしい文字列でも、一般名詞・除外対象・文断片なら抑制し、場所や月を含む弱い候補として扱う。
- **なぜ**: 曖昧な単語を固有イベントとして採用すると、異なる行事の根拠が混ざるから。
- **破れたときの症状**: 存在しないイベント名の候補が増え、別会場の情報が誤結合される。
- **守っているコード**: `collection_support/event_evidence.py` の `is_generic_event_hint()` と `classify_event_evidence()`
- **守っているテスト**: `tests/test_event_evidence.py::test_generic_event_name_is_suppressed_and_uses_venue_month`

### INV-XPE-001 X投稿抽出は意味で捨てず、本文外の事実を通さない

- **内容**: `build_x_extraction_packets.py` はX投稿を語彙で除外せず、既処理・24時間以内に発行済み・完全重複だけを除く。`apply_x_extraction_results.py` は5点回答の日付・会場・引用・URLを本文とpacketに照合し、失敗時はレポートを作らない。5点未満も採点として保存する。
- **なぜ**: 発見の入口で意味判定を重ねると開催情報を取りこぼし、反対にLLMの書き写しを無検証で通すと正本候補へ捏造が混ざるため。
- **破れたときの症状**: 開催情報が読まれない／本文に無い日付や会場の候補がレビュー受信箱へ流れる。
- **守っているコード**: `build_x_extraction_packets.py` の `build()`、`apply_x_extraction_results.py` の `apply()`
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_build_keeps_non_bon_post_and_state_reissue_rules`、`tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_invalid_quote_and_past_date_are_not_reports_but_are_applied`

### INV-XPE-002 本文に無い日付・会場・引用からレポートを作らない

- **内容**: 照合に失敗したイベントだけを除外し、同じ投稿の他イベントは巻き込まない。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_one_bad_event_does_not_discard_a_second_valid_event`

### INV-XPE-003 5点未満からE0レポートを作らない

- **内容**: 4点以下からE0レポートを作らない。ただし点数は `data/x_post_scores.json` に必ず残し、
  本文由来の曲claim・界隈語も各観測台帳へ残す。
- **なぜ**: 点数は捨てるための閾値ではなく、後で並べ替え・見直しをするための記録だから（2026-08-15 内田さん）。
- **破れたときの症状**: 読んだ結果や低得点投稿の曲材料が消え、同じ投稿を読み直す羽目になる。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_unknown_no_is_flagged_and_low_scores_keep_only_the_score`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_events_songs_are_kept_when_score_is_not_five_without_e0_report`

### INV-XPE-004 生成レポートは出典URLを持つ

- **内容**: URLの無い投稿は候補化しない。
- **なぜ**: 出典なしで正本factの材料を作らないため。
- **破れたときの症状**: 出所を辿れない開催情報がレビュー受信箱へ入る。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_post_without_url_never_becomes_a_report`

### INV-XPE-005 投稿由来の会場に住所を推測しない

- **内容**: `venue` は名称とareaだけである。
- **なぜ**: 投稿から住所は読めず、推測を入れると `ensure_venue` の完全一致照合を誤らせる。
- **破れたときの症状**: 同じ会場が住所違いで二重に登録される（2026-08-07 鹿骨中学校と同型）。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_report_omits_address_and_derives_year_from_date`

### INV-XPE-006 私人アカウントを公開詳細へ出さない

- **内容**: 私人のアカウント名・ハンドルはdetail_addendumへ入れない。URLは公開層が除去する内部記録行にだけ残す。
- **なぜ**: 本人の同意なく私人の投稿を公開サイトへ引用しないため（2026-08-08 内田さん決定）。
- **破れたときの症状**: 公開ページに第三者のXハンドルが並ぶ。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_apply_fails_closed_and_bundles_without_replacing_source`

### INV-XPE-007 未回答投稿は24時間後に再発行し、処理済みは掘り返さない

- **内容**: issuedだけの投稿は処理済みにせず24時間後に再びパケット化する。`applied_at` を持つ投稿は `--reissue` でも出さない。
- **なぜ**: 読み落としを取りこぼさないため。逆に処理済みを再発行すると、同じ投稿を何度も読ませることになる。
- **破れたときの症状**: 回答が返らなかった投稿が永久に読まれない／既に読んだ投稿が毎日パケットへ戻る。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_applied_post_is_never_reissued_even_with_reissue_flag`、`tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_build_keeps_non_bon_post_and_state_reissue_rules`

### INV-XPE-008 束ねたXレポートは代表投稿を変えない

- **内容**: 同じ正規化済み名前・日付・会場の投稿は1 report_idへ束ね、初回の `source.url` / `raw_text` / `events` を固定し、後続URLだけ内部記録行へ追記する。
- **なぜ**: 代表を入れ替えるとE0のsource payload hashが変わり、実質同一候補に無意味なrevisionが増えるため。
- **破れたときの症状**: 同じ開催情報を再取り込みしただけでレビュー候補が増える。
- **守っているコード**: `apply_x_extraction_results.py` の `apply()`
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_bundle_keeps_first_representative_and_never_rewrites_events`、`tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_apply_fails_closed_and_bundles_without_replacing_source`

### INV-XPE-009 累積voicesから読ませるのは既定で前日以降だけ、超過分は次回へ残す

- **内容**: `build()` は `--since`（既定＝前日）以降の投稿だけを対象にし、`--max-batches`（既定10）で1回の出力を制限する。上限を超えた投稿には `issued_at` を書かないので、次回そのままパケットへ出る。
- **なぜ**: `voices.json` は日次の差分ではなく**累積**で、2026-08-16 時点でX系だけで32,476件ある。下限を置かないと初回実行が102バッチ（30,557件）になり、判定が回らない。実測では前日以降だけで3バッチ（778件）に収まる。
- **破れたときの症状**: 初回や再構築のたびに数万件のパケットが生成され、判定が事実上不可能になる／上限で切った分が捨てられて二度と読まれない。
- **守っているコード**: `build_x_extraction_packets.py` の `build()`
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_since_defaults_to_yesterday_and_max_batches_defers_the_rest`

### INV-XPE-010 曲claim・界隈語は投稿本文に書かれた材料だけを観測する

- **内容**: `apply_x_extraction_results.py` は曲名・曲ごとの `claim_type`・根拠引用と界隈語を受け入れ、
  NFKC正規化と空白・中黒・長音の除去後に曲名と引用が投稿本文にあり、引用内にも曲名があることを照合する。
  ひらがなとカタカナは同一視しない。照合できない1要素はissueへ落とし、同じ回答の他要素を巻き込まない。
- **なぜ**: LLMが本文に無い曲名や用語を補完すると、未確認情報が観測台帳へ事実のように蓄積されるから。一方、表記上の中黒・長音・全半角差だけで本文由来の語を落とすと、実在する観測を失うから。
- **破れたときの症状**: 本文に無い曲・語が候補化される／「ダンシング・ヒーロー」と「ダンシングヒロ」のような表記差で観測が消える／ひらがな・カタカナの別語が誤結合される。
- **守っているコード**: `apply_x_extraction_results.py` の `_material_text()`、`_appears_in_text()`、`_record_materials()`
- **守っているテスト**: `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_01_records_song_found_in_text`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_bad_claim_quotes_fail_per_song`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_12_normalizes_middle_dot_long_mark_and_width`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_13_does_not_fold_hiragana_and_katakana`

### INV-XPE-011 第1段の曲名観測は曲マスタや開催回へ自動接続しない

- **内容**: E0X-Sの第1段は `data/x_song_observations.json` に原文由来の観測を積むだけで、`songs`、`song_aliases`、`occurrence_songs`、`event_occurrences` を読まず、書かない。`event_name` が無い観測も `null` のまま保持する。
- **なぜ**: 同名曲、表記揺れ、行事不明の投稿があるため、文字列抽出と曲の同一性判断・開催回への紐付けを一度に行うと誤結合が正本へ入るから。
- **破れたときの症状**: 投稿に曲名があっただけで、別の曲や開催回へ自動登録される。
- **守っているコード**: `apply_x_extraction_results.py` の `_record_song_group()` と `_record_materials()`
- **守っているテスト**: `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_04_records_null_event_name`、`tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_17_has_no_occurrence_songs_write_path`

### INV-XPE-012 同じ回答を再取り込みしても観測件数を増やさない

- **内容**: v2曲claimは投稿・行事文脈・曲名・根拠引用からfamily IDを、そこへclaim typeを加えて観測IDを作る。
  旧文字列回答は従来IDを保つ。界隈語観測は全件の `source_tweet_ids` を保持し、`count` をその配列の長さから導出する。
  表示用の `examples` は5件で止めても、重複判定の根拠は失わない。
- **なぜ**: 回答の再送や再実行は通常運用で起きる。例示上限を重複判定に兼用すると、6件目以降の再取り込みで件数だけが増え続けるから。
- **破れたときの症状**: 同じ投稿を再処理するたびに曲観測や用語のcountが増える。
- **守っているコード**: `apply_x_extraction_results.py` の `_record_song_group()` と `_record_glossary()`
- **守っているテスト**: `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_is_idempotent_and_conflicting_reanswer_is_held`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_legacy_rows_get_defaults_without_new_identity`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_18_glossary_count_is_idempotent_after_examples_fill`

### INV-XPE-013 曲claim・界隈語の壊れた要素は採点・レポート・他観測を止めない

- **内容**: `observations`、各観測、`songs`、`glossary` の型不正は要素単位のissueにし、既存の採点、5点イベントレポート、同じ投稿の正常な曲名・界隈語を処理し続ける。取り込みレポートは曲名と界隈語のissue件数を分けて残す。
- **なぜ**: 補助的な観測の形式不正で既存E0X経路まで失敗すると、開催情報の取り込みと再現可能な採点記録を同時に失うから。
- **破れたときの症状**: 1曲の型不正で投稿全体の採点・レポートが消える／どちらの観測が壊れたかレポートから判別できない。
- **守っているコード**: `apply_x_extraction_results.py` の `_record_materials()` と `apply()`
- **守っているテスト**: `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_03_keeps_valid_song_when_sibling_is_invalid`、`tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_14_malformed_observations_do_not_stop_other_processing`、`tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_20_bad_event_name_does_not_stop_glossary_or_scoring`、`tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_21_bad_glossary_does_not_stop_song_score_or_report`、`tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_acceptance_25_separates_song_and_glossary_issue_counts`

### INV-XPE-014 曲の意味はoriginでなく曲ごとのclaim typeで持つ

- **内容**: `announced` / `observed` / `mentioned` / `unknown` は各 `song_claims[]` に置く。
  `events` / `observations` という回答上の経路は来歴だけであり、意味へ変換しない。
- **なぜ**: 同じ行事の実績曲と願望曲が一投稿に混在し、置き場所だけでは意味を決められないから。
- **破れたときの症状**: 「来年はこの曲もやってほしい」が実績曲や告知曲として扱われる。
- **守っているコード**: `apply_x_extraction_results.py` の `_record_song_group()`
- **守っているテスト**: `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_mixed_claims_keep_per_song_meaning`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_origin_does_not_override_claim_type`

### INV-XPE-015 曲claimのE0系譜は実在するイベント要素だけを指す

- **内容**: 5点イベントが検査を通ってレポートが生成・再利用された場合だけ、曲claimへreport ID、
  event entry ID、E0 family keyを付ける。過去日・URL欠落・本文照合失敗では付けない。
- **なぜ**: report IDだけでは複数要素を区別できず、生成前に予測したIDは存在しない開催回へのdangling参照になるから。
- **破れたときの症状**: 曲claimが別行事のE2判断へ結び付く／存在しないE0候補を待ち続ける。
- **守っているコード**: `apply_x_extraction_results.py` の `apply()` と `_report_event_id()`
- **守っているテスト**: `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_valid_five_point_event_has_real_e0_dependency`、
  `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_rejected_event_keeps_claim_without_dangling_dependency`

### INV-XPE-016 claim再回答の意味競合を自動公開へ流さない

- **内容**: 同じ投稿・行事文脈・曲・根拠引用でclaim typeだけが異なる回答は、同じfamilyの別観測として保持し、
  `claim_type_conflict=true` とissueを残す。黙って上書きしない。
- **なぜ**: LLM再実行の揺れを最後の回答で上書きすると、根拠なしに告知と実績が入れ替わるから。
- **破れたときの症状**: 同じ原文の再処理だけで公開根拠ラベルや曲の役割が変わる。
- **守っているコード**: `apply_x_extraction_results.py` の `_mark_claim_conflicts()`
- **守っているテスト**: `tests/test_x_post_extraction_songs.py::XPostExtractionSongsTest::test_v2_is_idempotent_and_conflicting_reanswer_is_held`

## 主要な流れ

1. 文面から時期・地域・会場・曲・団体・界隈語を抽出する。
2. `apply_x_extraction_results.py` が本文照合を行い、曲ごとのclaim・行事文脈・根拠引用と界隈語を
   それぞれの観測台帳へ冪等に記録する。実在するE0レポートがある曲claimだけ、そのイベント要素の系譜を持つ。
3. 除外語と盆踊り文脈を評価し、理由つきの点数を計算する。
4. 同一候補を関連キーでまとめ、優先候補としてレビューへ渡す。曲名・界隈語の観測はこの段階では正本や開催回へ結び付けない。

## 依存と影響

上流の原文が無ければ判断の再現性はない。下流のレビューは、ここで残す根拠と「未確認」という状態を前提に採否を決める。

## 壊れたときの症状

無関係候補が増えたら除外語・文脈減点を、候補が結合し過ぎるなら関連キーと固有名の抑制を確認する。

## 未解決・注意点

スコアは真実性の証明ではない。公式確認や人の承認を省略する根拠にはならない。曲名・界隈語の観測台帳も同様に「投稿本文にこの文字列があった」という記録であり、曲の同一性、開催回との関係、用語の自動適用可否を確定しない。第2段の照合・レビュー経路は未実装である。詳細は [E0X-S設計](../../x-post-extraction-songs-v1.md) を参照する。

---

おと（Codex）
