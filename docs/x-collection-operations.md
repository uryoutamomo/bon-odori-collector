# X収集の運用（情報源・ポスター画像）

2026-07-26に「Xからの情報を拾えていない／重要な盆踊ラーを把握できていない／管理する
コンソールがない」という指摘を受けて手を入れた。ここでは、そのとき何が詰まっていたのかと、
今どういう形で回っているのかを残す。

## 何が詰まっていたか（2026-07-26 時点の実測）

| 症状 | 実測 | 原因 |
| --- | --- | --- |
| 検索が浅い | 1日216件・$0.063（日次予算$3.0の2%） | `max_pages_per_query: 3` で主要クエリが毎回3ページとも満杯のまま打ち切り |
| ポスターを読んでいない | `event_poster_ocr_queue.json` 1789件が全て `needs_ocr` | キューを生成するだけで、消費するコードがリポジトリに存在しなかった |
| 情報源が増えない | 収集名簿69件 / スコア台帳の `trusted` 383件 | 名簿の供給源がNotion「Xメンバーリスト」だけで、スコアが高くても手で登録するまで読みに行かなかった |
| 発見が止まっていた | `discover_x_social_graph` 最終実行 2026-06-06、`review_x_candidate_posts` 最終 06-09 | どちらも `workflow_dispatch` 専用で、誰も手で起動していなかった |
| 一覧する画面がない | — | レビューコンソールはイベント・曲・YouTube審査のみを扱っていた |

## 収集対象アカウントの決まり方

正本は**ローカル**。Notionは移行期間の任意フォールバックで、読めなくても収集は成立する。

1. `data/x_official_source_accounts.json` — 公式・主催アカウント
2. `data/x_important_informants.json` — 重要情報提供者（手動登録・最優先）
3. `data/x_collection_roster.json` — 収集名簿の正本（Notionから移行）
4. スコア台帳 `data/x_account_scores.json` の `trusted` を自動編入
   （`x_queries.json` の `auto_trusted_roster`。既定 最大250件・`posts_seen>=3`・スコア6.0以上）
5. Notion「Xメンバーリスト」（任意・失敗しても続行）

`manual_status` は `優先`（毎回必ず読む） / `通常`（スコア順） / `休止`（読まない）。

Notionから名簿を取り込み直したいときだけ `python3 export_x_member_roster.py` を実行する
（`NOTION_API_TOKEN` が必要。ローカルで手を入れた `manual_status` は上書きしない）。

## ポスター画像の読み取り

キューは日次で `build_event_poster_ocr_queue.py` が作る。**開催日が未確定のイベント**
（`date_start` が空）に触れている投稿を先頭に並べる。公開サイトで地図に出せていないのは
この「開催日が分からない」イベントなので、読めば直接埋まるため。

```sh
# 1. 未確定イベントに一致した投稿の画像だけ落とす
python3 fetch_poster_images.py --gap-only --priority all --limit 40

# 2. こと（Claude Code）が data/poster_images/ の画像を Read で読み、
#    data/poster_images/manifest.json の本文と突き合わせて内容を確認する

# 3. 読み取れたイベント情報は掲示物レポートとして master RDB へ入れる
#    （手順は docs/official-notice-field-report-operations.md）

# 4. 読んだ投稿を台帳に記録し、次回から未読キューに出ないようにする
python3 apply_poster_ocr_decisions.py --apply
```

会場名が一致しても別イベントのことがあるので、機械的な一致だけで日付を書き込まない。
2026-07-26の実例では、亀有ゆうろーどで7月と8月に主催町会の違う別の盆踊りがあり、
上野恩賜公園では同じ会場で複数の異なるイベントが並行していた。

読み取り済みの記録は `data/poster_ocr_processed.json`（`ocr_done` / `ocr_no_event` /
`ocr_unreadable`）。キューは毎日作り直されるため、この台帳が「読んだかどうか」の正本になる。

## レビューコンソール

```sh
python3 review_console_ops/run_review_console.py
```

- **X情報源アカウント一覧** — 誰を読んでいるか、なぜ名簿に入っているか、投稿の質、
  最終投稿からの日数。優先/通常/休止をここで決める。
- **ポスター画像の読み取り待ち** — 未読の画像投稿。読んだ結果をここで記録する。

決定の反映は既存の流儀どおり2段階：

```sh
python3 review_console_ops/apply_review_console_decisions.py --write   # 決定をstaged化
python3 apply_x_roster_decisions.py --apply                            # 名簿へ反映
python3 apply_poster_ocr_decisions.py --apply                          # 読み取り台帳へ記録
```

`apply_x_roster_decisions.py` はNotionへ書き込まない。Notion「Xメンバーリスト」への
追加・同期は内田さんが承認した候補だけに限る運用のため（CLAUDE.md）。

## 定期実行

| workflow | 実行時刻 | 内容 |
| --- | --- | --- |
| `collect.yml` | 毎日 15:13 JST | 収集・ポスターキュー生成・アカウント一覧生成 |
| `discover_x_social_graph.yml` | 毎週火曜 6:00 JST | フォローグラフから候補アカウントを発見 |
| `review_x_candidate_posts.yml` | 毎週火曜 6:30 JST | 候補を過去投稿の質で審査 |

後者2つはスケジュール実行時のみ確認文字列の入力を省略する。Notionメンバーリストへの
昇格同期（`sync_only`）は自動実行しない。

## 予算

`x_queries.json` の `budget`。日次$3.0（据え置き）/ 月次$25.0（2026-07-26に15から引き上げ）。
月次を上げたのは、探索深度とクエリ本数を増やした結果、月内に上限へ当たって収集が
全停止する事故を避けるため。実効的な安全弁は日次の方。

予算停止の正本は従来どおり `data/x_budget.json` である。日別合計だけを持つこの形式は
既存のguardとの互換性のため変えない。改善前後の費用と成果を比較する詳細台帳は
`data/x_cost_ledger.json` に追記する。

- 経路: `search`（query ID別）/ `whitelist` / `cohort_evidence` /
  `candidate_probe` / `social_graph`（加えて能動検索が動いた場合は `proactive`）
- 成果: API request数、取得件数、新規URL数、voices採用件数、証拠断片数、候補発見・昇格数
- 同じ日・同じ経路の再実行も別エントリとして残す。台帳を上書き集計しないので、後から
  失敗・再実行を含めて費用を検証できる。

2026-08-11以前に経路別の機械記録はなかったため、同日Actionsログの手計測を初期行として
登録している。内訳合計と共有予算台帳との差額は `unattributed` として明示し、推測で配分しない。

## 検索クエリの読み取り位置（2026-08-16〜）

検索は取得件数ぶんだけ課金される。従来は11本のクエリを毎回1ページ目から読み直していて、
既読URLは保存の段で捨てていたが**課金は発生していた**（2026-08-11 の実測で1,760件中1,100件が読み直し）。

いまはクエリごとに「ここまで読んだ」時刻を `data/x_query_watermarks.json` に持ち、
`since_time:` を付けてその先だけを読む。設定は `x_queries.json` の `search_watermark`。

| 設定 | 既定 | 意味 |
| --- | --- | --- |
| `enabled` | `true` | `false` にすると従来の全件読み直しへ戻る（退避路） |
| `initial_lookback_days` | `3` | 記録が無いクエリを何日さかのぼって読むか。**クエリを新設したときだけ効く** |
| `overlap_minutes` | `60` | 窓の境目で落とさないための重なり幅 |
| `stop_after_zero_new_page` | `true` | 新規0件のページに達したらそのクエリを打ち切る |

**読み切れなかったクエリは窓を進めない**（ページ上限で切れた／HTTP失敗）。
これは名簿の直読みと同じ約束で、進めるとその時間帯が二度と検索されなくなるため（INV-COL-006）。
どのクエリが読み切れたかは `data/x_cost_ledger.json` の `note`（`since_time:... completed:True/False`）で分かる。

- **取りこぼしが疑われるとき**: `completed:False` が続くクエリは、`x_queries.json` の
  `queries[].max_pages` でそのクエリだけページ上限を上げる（全体の `max_pages_per_query` は据え置ける）。
- **窓をやり直したいとき**: `data/x_query_watermarks.json` から該当クエリの行を消すと、
  次回は `initial_lookback_days` 前から読み直す。ファイルごと消しても壊れない（初回扱いになるだけ）。
