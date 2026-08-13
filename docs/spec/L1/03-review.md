---
id: L1-review
layer: L1
title: 人のレビュー運用サブシステム
owns:
  - review_inbox.py
  - review_inbox_adapters/**
  - review_console/**
  - review_console_ops/**
  - scripts/promote_change_requests_for_review.py
depends_on:
  - L1-master
invariants:
  - INV-RVW-001
  - INV-RVW-002
  - INV-RVW-003
  - INV-RVW-004
verified_by:
  - tests/test_review_inbox_decision_writer.py
  - tests/test_promote_change_requests_for_review.py
updated_for: 6537e7f
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

## 主要な流れ

1. **各アダプタが受信箱へ積む** — `review_inbox_adapters/` 配下。X由来の穴、公式ソース、
   会場欠落、過去実績、YouTube など、種類ごとに別アダプタになっている。
2. **受信箱を投影する** — `review_inbox.py --out-json data/review_inbox.json --status pending`。
3. **人が裁定する** — `review_console_ops/run_review_console.py` でローカルサーバを立て、
   `review_console/` のUIで判断する。
4. **決定を書く** — `review_inbox_adapters/decision_writer.py`（INV-RVW-001〜003）。
5. **昇格させる** — `scripts/promote_change_requests_for_review.py` を人が実行（INV-RVW-004）。
6. **マスタへ適用** — [L1-master](04-master.md) の dry-run → apply 経路へ。

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
- レビューコンソールの「次に何をすべきか」の提示が弱く、優先順位が人の記憶に依存している。
- アダプタが種類ごとに増える構造なので、共通の契約（L2）を切り出したい。

---

こと（Claude Code）
