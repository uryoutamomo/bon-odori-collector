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
