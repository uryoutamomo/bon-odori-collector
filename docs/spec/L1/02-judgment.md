---
id: L1-judgment
layer: L1
title: 自動判断サブシステム
owns:
  - collection_support/event_evidence.py
  - collection_support/suppression_rules.py
  - collection_support/tokyo23_scope.py
  - collection_support/x_source_officiality.py
depends_on:
  - L1-collection
invariants:
  - INV-JDG-001
  - INV-JDG-002
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
