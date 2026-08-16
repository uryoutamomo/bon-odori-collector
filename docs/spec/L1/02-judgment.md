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
verified_by:
  - tests/test_event_evidence.py
updated_for: 6537e7f
---

# 自動判断サブシステム

> 上位は[全体地図](../README.md)。これは自動採用器ではなく、観測を説明可能な優先候補へ整える工程である。

## この工程は何のためにあるか

収集された文章から日付・場所・イベント名などの根拠を取り出し、人が確認すべき候補を優先付けする。弱い断片を消して「なかったこと」にするより、弱い理由を残して人が判断できるようにする。

## 入力と出力

入力は収集済みの投稿と除外語・地理・公式性の設定。出力はイベント候補の本文、根拠、スコア、推定日付・会場・関連キーである。

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

### INV-XPE-003 5点未満は採点だけを保存する

- **内容**: 4点以下からE0レポートを作らない。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_invalid_quote_and_past_date_are_not_reports_but_are_applied`

### INV-XPE-004 生成レポートは出典URLを持つ

- **内容**: URLの無い投稿は候補化しない。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_invalid_quote_and_past_date_are_not_reports_but_are_applied`

### INV-XPE-005 投稿由来の会場に住所を推測しない

- **内容**: `venue` は名称とareaだけである。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_apply_fails_closed_and_bundles_without_replacing_source`

### INV-XPE-006 私人アカウントを公開詳細へ出さない

- **内容**: 私人のアカウント名・ハンドルはdetail_addendumへ入れない。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_apply_fails_closed_and_bundles_without_replacing_source`

### INV-XPE-007 未回答投稿は24時間後に再発行する

- **内容**: issuedだけの投稿は処理済みにせず、24時間後に再びパケット化できる。
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_build_keeps_non_bon_post_and_state_reissue_rules`

### INV-XPE-008 束ねたXレポートは代表投稿を変えない

- **内容**: 同じ正規化済み名前・日付・会場の投稿は1 report_idへ束ね、初回の `source.url` / `raw_text` / `events` を固定し、後続URLだけ内部記録行へ追記する。
- **なぜ**: 代表を入れ替えるとE0のsource payload hashが変わり、実質同一候補に無意味なrevisionが増えるため。
- **破れたときの症状**: 同じ開催情報を再取り込みしただけでレビュー候補が増える。
- **守っているコード**: `apply_x_extraction_results.py` の `apply()`
- **守っているテスト**: `tests/test_x_post_extraction_e0x.py::XPostExtractionE0XTest::test_apply_fails_closed_and_bundles_without_replacing_source`

## 主要な流れ

1. 文面から時期・地域・会場・曲・団体を抽出する。
2. 除外語と盆踊り文脈を評価し、理由つきの点数を計算する。
3. 同一候補を関連キーでまとめ、優先候補としてレビューへ渡す。

## 依存と影響

上流の原文が無ければ判断の再現性はない。下流のレビューは、ここで残す根拠と「未確認」という状態を前提に採否を決める。

## 壊れたときの症状

無関係候補が増えたら除外語・文脈減点を、候補が結合し過ぎるなら関連キーと固有名の抑制を確認する。

## 未解決・注意点

スコアは真実性の証明ではない。公式確認や人の承認を省略する根拠にはならない。

---

おと（Codex）
