# bon-odori-collector

盆踊り関連ニュースを Google News RSS から収集し、結果を Notion ページへ自動反映する仕組み。

## 構成

- `collect.py` — RSS 収集 + Notion 書き込み（標準ライブラリのみ、依存追加なし）
- `.github/workflows/collect.yml` — 毎日 15:13 JST（cron `13 6 * * *`）+ 手動実行で `collect.py` を実行
- `send_mail.py` — `data/pending_mail.json` を Gmail SMTP で送信する日刊メール配信
- `.github/workflows/send_mail.yml` — 18:23 / 19:23 / 20:23 JST に冪等実行し、送信成功後に `pending_mail.json` を削除
- `data/latest.json` — 最新スナップショット（現在取得できた全件）
- `data/seen.json` — これまでに見た URL の履歴（累積）

## 動作の要点

- **`latest.json` は「現在取得できた記事の全件スナップショット」**。差分（新着のみ）ではない。
  以前は新着のみを書く実装で、`seen.json` が埋まると `[]` になる問題があった（2026-05-29 に全件方式へ変更）。
- `seen.json` は履歴として累積し続ける（重複検知用に保持）。

## Notion 連携（重要）

- 書き込み先ページ: **「🤖 GitHub収集データ（最新）」**
  - Page ID: `36e8be04-e762-8188-a4e0-d8cc6e6f263c`
  - 親: 「🏮 盆踊りプロジェクト 2026」
- `collect.py` が毎回ページの子ブロックを全削除 → 最新内容で再構築する
  （セクション: 最終更新 / 収集データ(JSON) / ステータス）
- このページは GitHub Actions が自動管理する。**手動編集しないこと。**

### 必要な GitHub Secrets

| Secret | 用途 |
|---|---|
| `NOTION_API_TOKEN` | Notion インテグレーション（内部）のアクセストークン |
| `NOTION_PAGE_ID` | 書き込み先ページの ID |
| `TWITTERAPI_IO_KEY` | X(twitterapi.io) 収集用キー。**未設定なら X 収集はスキップ**（fail-safe） |

Notion インテグレーション `bon-odori-collector` が対象ページに共有されている必要がある。
トークン未設定時は書き込みをスキップして収集だけ行う（クラッシュしない）。

## メール配信（NotionドラフトDB不使用）

- 配信本文は `data/pending_mail.json` に置く。
  - フォーマット: `{"subject": "...", "html": "完全なHTML文字列", "plain": "プレーンテキスト"}`
- `send_mail.py` は `pending_mail.json` が存在する時だけ送信する。
- 送信成功後、`send_mail.yml` が `pending_mail.json` を削除してコミット・プッシュする（二重送信防止）。
- `pending_mail.json` が存在するのに設定不足・本文空などで送信できない場合は非ゼロ終了し、ファイルを残す。

## X(twitterapi.io) 収集（「人の言葉」）

X API 廃止で止まっていた参加レポ・感想の収集を、非公式プロキシ **twitterapi.io**（$0.15/1000件のプリペイド）で復活させたもの。`collect.py` の `collect_x_voices()` が担当。

- **設定は `x_queries.json` に外出し**（クエリ・除外語・体験語・予算）。コードを触らず実験できる。
- **自動仕分け**: 除外語ヒット→🔴ノイズ／体験語ヒット→🟢一次レポ／それ以外→🟡関心。ノイズは `voices.json` に流さない。
- **全件を Notion「🐦 X収集ログ DB」(`ef2f627d-…`) に1行ずつ記録**。`正解ラベル`(👍/👎/未評価) を手で付けて除外語を育てる改善ループ用。
- **安全装置**: 予算上限（日次/月次, `data/x_budget.json` に消費を累積記録しコミットして実行をまたいで効かせる）・429ウェイト・例外を他収集に波及させない fail-safe。
- 設計の詳細は Notion「盆踊り情報開発 >『X収集 改善ループ 設計アイデア』」。
- `experiment_x_voices.py` は本番統合前の使い捨て実証スクリプト（記録として残置）。

### Xメンバーリストのスコア運用

- 過去のX投稿から `data/x_account_scores.json` を生成し、Notion「X メンバーリスト」DBへスコアを書き戻す。
- 価値判定は、未来の開催予定・日時・会場・告知/ポスターを強く加点する。ただし参加レポ、感想、写真/動画つき投稿も価値ありとして残す。
- Notion側で人間が調整できる項目:
  - `収集ステータス`: `優先` / `通常` / `休止`
  - `手動重み`: 自動スコアに加算する数値
- collectorが書き戻す項目:
  - `自動スコア`, `収集ランク`, `投稿数`, `価値投稿数`, `未来予定投稿数`, `最終評価日時`, `評価理由`
- `休止` または自動 `muted` のアカウントは通常巡回から外す。ただし設定で少数の再確認枠を残せる。

### Xフォローグラフによる候補発見

- `discover_x_social_graph.py` は、高スコアseedアカウントの followings から未知の候補アカウントを発見する手動実験用スクリプト。
- 実行は `.github/workflows/discover_x_social_graph.yml` の `workflow_dispatch` のみ。通常収集にはまだ混ぜない。
- 出力:
  - `data/x_social_graph.json`: seed→候補のfollowingエッジと概算コスト
  - `data/x_candidate_accounts.json`: review用の候補リスト
- 重要: つながりの多さは「良い盆踊ラー」判定の主軸にしない。あくまで漏れ発見の補助信号。
- 本採用や優先度判断は、候補の過去投稿に未来予定・会場/日時・告知/ポスター・感想/写真がどれだけあるかで決める。
- `review_x_candidate_posts.py` は、候補上位の最新投稿を見て投稿価値で絞り込む第2段階。
  - 投稿取得は通常収集と同じ `advanced_search` の `from:handle` 検索を使う。
  - 実行は `.github/workflows/review_x_candidate_posts.yml` の `workflow_dispatch` のみ。
  - 出力は `data/x_candidate_post_review.json`。
  - `promote` は昇格候補、`watch` は保留、`reject` は投稿価値が薄い候補。
  - `promote` は重複を避けてNotion「X メンバーリスト」へ `通常` で自動追加する。
  - 追加後は通常の投稿価値スコアで再評価し、低評価なら自動 `muted` で周回対象から外す。
  - 保存済み結果だけ再同期する場合はWorkflowの `sync_only=true` を使う（X API課金なし）。

## この仕組みの思想

Claude が動いていなくても GitHub Actions が自律実行し、Notion が更新され続ける。
スケジュール実行のたびに Claude が動く Cowork とは役割が異なる。
