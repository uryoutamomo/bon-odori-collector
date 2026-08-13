---
id: L1-collection
layer: L1
title: 収集サブシステム
owns:
  - collect.py
  - collection_support/x_raw_archive.py
  - collection_support/x_budget_guard.py
  - collection_support/x_cost_ledger.py
  - collection_support/x_collection_health.py
  - collection_support/x_source_registry.py
  - collection_support/x_author_profile.py
  - collection_support/x_official_source_accounts.py
  - collection_support/voices_s3_artifact.py
  - voices_s3_artifact.py
  - collect_venue_sites.py
  - venue_sites.json
  - build_x_gap_candidates.py
  - discover_x_social_graph.py
  - sync_x_promoted_members.py
  - sync_weekly_costs.py
depends_on: []
invariants:
  - INV-COL-001
  - INV-COL-002
  - INV-COL-003
  - INV-COL-004
verified_by:
  - tests/test_x_raw_archive.py
  - tests/test_x_collection_health.py
updated_for: 83bf7d0
---

# 収集サブシステム

> 上位は[全体地図](../README.md)。収集は候補と観測を集める工程であり、採否を決める工程ではない。

## この工程は何のためにあるか

RSS、YouTube、X、公式ソースから、盆踊りに関係しうる情報を失わず集める。外部APIは欠損や失敗が普通に起きるため、失敗を「情報なし」と取り違えず、次の判断工程へ根拠と状態を渡すことが責務である。

## 入力と出力

入力は各サービスの取得結果、既読URL、X設定、予算状態、および会場公式サイトの監視設定（`venue_sites.json`）である。出力は `data/voices.json`、`data/latest.json`、生X投稿のアーカイブ、収集状態・コスト台帳、および候補キューである。

## 不変条件

### INV-COL-001 Xの生投稿は意味判定より先に保存する

- **内容**: 未見のX投稿は `_prepare_new_x_posts()` が `capture_raw_x_posts()` で保存に成功してから後続の仕分けへ渡す。保存失敗時は既読を進めない。
- **なぜ**: 分類ルールは後で直せるが、取りこぼした原文は復元できないから。
- **破れたときの症状**: 判定規則を直しても過去投稿を再評価できず、候補が静かに欠落する。
- **守っているコード**: `collect.py` の `_prepare_new_x_posts()`、`collection_support/x_raw_archive.py`
- **守っているテスト**: `tests/test_x_raw_archive.py::test_archive_failure_propagates_without_seen_advance`

### INV-COL-002 同じURLを1回の収集で重複して取り込まない

- **内容**: `_prepare_new_x_posts()` は既読集合・今回の既読予定集合・今回の準備済みURLを照合して重複を除く。
- **なぜ**: 同じ投稿の重複は候補の件数と重要度を水増しし、後段の人の判断を歪めるから。
- **破れたときの症状**: 同一投稿が複数の候補として並び、レビュー件数とXコストの説明が合わなくなる。
- **守っているコード**: `collect.py` の `_prepare_new_x_posts()`
- **守っているテスト**: `tests/test_collect_duplicate_urls.py::test_prepare_new_x_posts_excludes_duplicate_seen_new_seen_and_empty_urls`

### INV-COL-003 収集不能・受理0件を正常な「投稿なし」として扱わない

- **内容**: `collect_x_voices()` はキー・設定・予算が欠けると理由つきで安全にスキップする。さらに `finalize_health_report()` は、収集が必要なのに無効だった場合と、成功扱いでも受理0件だった場合を `unhealthy` にする。
- **なぜ**: 2026-08-10のtwitterapi.io課金切れでは、HTTP上は成功しても取得が空だった。止めるだけでは障害を「投稿なし」と取り違えるため、空を異常として見える化しなければならない。
- **破れたときの症状**: API費用が予想外に増える、または収集停止・受理0件が正常終了に見えて探索の穴が何日も続く。
- **守っているコード**: `collect.py` の `collect_x_voices()`、`collection_support/x_budget_guard.py`、`collection_support/x_collection_health.py` の `finalize_health_report()`
- **守っているテスト**: `tests/test_x_collection_health.py::test_successful_but_zero_item_run_is_unhealthy`、`tests/test_x_collection_health.py::test_measured_scheduled_outage_is_unhealthy_for_402_and_zero_items`

### INV-COL-004 未完了のホワイトリスト収集では since_time を進めない

- **内容**: `collect_whitelist_voices()` は、全バッチが完了したときだけ次回検索の `since_time` を保存する。402などで一部でも未完了なら従来の時刻を維持する。
- **なぜ**: `since_time` を先に進めると、その時間窓の投稿は次回以降の検索対象から外れ、取りこぼしが恒久化するから。
- **破れたときの症状**: 課金・通信障害の時間帯だけ候補が永久に消え、復旧後も再収集されない。
- **守っているコード**: `collect.py` のホワイトリスト収集と `since_time` 保存経路
- **守っているテスト**: `tests/test_x_collection_health.py::test_whitelist_402_after_partial_success_does_not_advance_since_time`、`tests/test_x_collection_health.py::test_whitelist_advances_since_time_only_after_every_batch_completes`

## 主要な流れ

1. `collect.py` がRSS・動画・Xを取得し、既読情報と照合する。
2. Xは生投稿をアーカイブしてから、候補・声・収集状態へ分ける。
3. `collect_venue_sites.py` が会場公式サイトを直接見に行き、`venue_sites.json` に登録されたRSS/HTMLから
   お知らせを取る。ニュースメディア経由では拾えない告知がここでしか取れないためで、
   取れたものは `source: "official_venue"` / `confirmed: true` を付けて `latest.json` へ合流する。
   1サイトの失敗が他サイトを止めない作りにしてある。
4. コストと健全性を記録し、候補は判断工程へ渡す。
5. `voices_s3_artifact.py`（中身は `collection_support/voices_s3_artifact.py` を呼ぶだけの互換入口）で、
   声をS3の成果物として受け渡す。日次の各workflowは処理の最初に `fetch --overwrite`、
   最後に `publish` を実行する。リポジトリに巨大なJSONを置かずに、複数のworkflowが同じ声を見るための仕組みである。

### 収集の穴と、読む相手を広げる経路（日次）

集めることと並んで、**集められていないものを見つける**のもこの工程の仕事である。
以下は日次で動いているが、2026-08-14まで仕様のどこにも属していなかった。

- `build_x_gap_candidates.py --limit 30` — 収集済みの投稿の中から、
  **公開データに無いイベントの話をしていそうなもの**を選ぶ。「穴」とはこの取りこぼしのことである。
  選んだ候補は[レビュー](03-review.md)側のアダプタとレーン分けへ渡る。取り出す件数を30に絞ってあるのは、
  人が裁定できる量を超えて積むと律速工程が詰まるためで、絞りの意味はレビュー側に書いてある。
- `discover_x_social_graph.py` — いま読んでいるアカウントの周辺から、新しく読むべき相手を探す。
  日次の `collect.yml` ではなく専用の workflow から動く。
- `sync_x_promoted_members.py` — 人が承認した「読む相手に加える」判断を、Xのメンバー台帳へ反映する。
  `review_x_candidate_posts.yml` から、候補の投稿を人が見る補助（`review_x_candidate_posts.py`、[レビュー](03-review.md)の持ち物）と対で動く。

読む相手が偏ると、特定の区だけ情報が薄くなるという形で症状が出る。
これは判定の精度の問題に見えるが、原因は入口の偏りであることが多い。

費用の記録は `sync_weekly_costs.py` が担う。`data/x_budget.json` を読んでNotionの費用DBへ週次で書き出すもので、
`weekly_harvest.yml` から動く。X収集は使った分だけ課金される仕組みなので、
**使いすぎだけでなく「払えていない」こともここに現れる**。2026-08-10の課金切れでは、
HTTP上は成功しているのに取得が0件という形で障害が出た（INV-COL-003）。

## 依存と影響

下流の判断とレビューは、収集の重複除去・生原文・失敗理由を前提にする。収集を「候補なし」と誤ると、下流は何も直せない。

## 壊れたときの症状

候補が急減したらAPIキー・予算・収集健全性を、同じ投稿が並ぶなら既読・URL正規化を、再評価できないならアーカイブを確認する。

## 未解決・注意点

外部サービスの応答品質はこの工程だけでは保証できない。取得なしと障害を区別する観測は引き続き強化が必要である。

---

おと（Codex）
