# bon-odori-collector

盆踊り関連ニュースを Google News RSS から収集し、結果を Notion ページへ自動反映する仕組み。

## 構成

- `collect.py` — RSS 収集 + Notion 書き込み（標準ライブラリのみ、依存追加なし）
- `.github/workflows/collect.yml` — 毎日 15:13 JST（cron `13 6 * * *`）+ 手動実行で `collect.py` を実行
- `send_mail.py` — `data/pending_mail.json` を Gmail SMTP で送信する日刊メール配信
- `.github/workflows/send_mail.yml` — 18:23 / 19:23 / 20:23 JST に冪等実行し、送信成功後に `pending_mail.json` を削除
- `data/latest.json` — 最新スナップショット（現在取得できた全件）
- `data/seen.json` — これまでに見た URL の履歴（累積）
- `data/proactive_event_report.json` — 定番イベントの今年情報の確認状況

## 動作の要点

- **`latest.json` は「現在取得できた記事の全件スナップショット」**。差分（新着のみ）ではない。
  以前は新着のみを書く実装で、`seen.json` が埋まると `[]` になる問題があった（2026-05-29 に全件方式へ変更）。
- `seen.json` は履歴として累積し続ける（重複検知用に保持）。

## Notion 連携（重要）

- 書き込み先ページ: **「🤖 GitHub収集データ（最新）」**
  - Page ID: `36e8be04-e762-8188-a4e0-d8cc6e6f263c`
  - 親: 「🏮 盆踊りプロジェクト 2026」
- `collect.py` が毎回ページの子ブロックを全削除 → 最新内容で再構築する
  セクション構成（上から順）:
  1. 📣 速報（新イベント候補） — ホワイトリスト声から未知イベントの速報
  2. 🔄 イベント更新（確度変化） — 既存会場へのX確認/中止シグナル
  3. 🔎 定番イベント確認 — 能動検索・公式情報源・抜け漏れ検出
  4. 🗣️ 人の言葉（X由来 / 配信ネタ） — 盆踊ラーの声
  5. 収集データ（JSON） — latest_items 全体
  6. ステータス / コスト
- このページは GitHub Actions が自動管理する。**手動編集しないこと。**

### 関連 Notion DB

| DB | ID | 用途 |
|---|---|---|
| 🎆 イベントDB | data source `a83b5a63-7411-4d6a-8bbc-83bedf4e7b5d` | イベント情報の現行の正本 |
| 🗓️ 参加計画 | data source `6a29d662-cd27-487f-9d76-5a57239b1aa2` | 個人の参加予定・検討情報の現行の正本 |
| 📖 盆踊ラー用語集 | `989e9effc7fc40db8043a3b8e03090ee` | 会場名などの表記ゆれ管理・名寄せ辞書 |
| 🔎 裏取りキュー | `f560afee832f4b1084d6e6093d74da16` | 新規検知会場の確認待ちキュー |
| 🏮 会場マスタ | `cbc56bda-2259-46bf-8aac-adb7efd691c2` | 既知会場の正式情報 |
| 💃 Xメンバーリスト | `5c585224465241548b631e4e5d316f3b` | ホワイトリスト盆踊ラー |

旧イベントマスター（data source `da4ba747-8702-4953-96e3-f25b518fb31a`）と
旧「盆踊りイベント（共通）」（data source `1d5b9eb2-33e0-4e9e-b3d5-7f9d0317943e`）
は移行済み・全行アーカイブ済み。参照・更新・新規作成に使用しない。
現行イベントDBから参加計画への旧relationは廃止済み。参加計画からイベントへの
`イベント` relationを正規の接続方向とする。

Notion正本IDは `notion_config.py` で一元管理する。イベント・参加計画を扱う
新規コードはData Source API（Notion-Version `2025-09-03`）を使用する。

イベントDBのスキーマ・重複監査:

```bash
python3 event_audit.py --fail-on-duplicates
```

- 正規化したイベント名の一致を重複候補として扱う。
- 同一情報源URLかつイベント名も高類似の場合は重複候補として扱う。
- 異なるイベントが一覧ページを共有しているだけの場合は警告に留める。
- GitHub Actionsの収集処理でも、収集開始前に同じ監査を実行する。

Google Calendar同期は `sync_gcal.py` を使用する。同期対象は、参加ステータスが
`参加予定` または `検討中`、イベント状態が `確認済み`、かつ `開催日` が設定済みの
レコードのみ。実行前に正本Data Sourceのスキーマ、relation接続先、イベント重複を
検査し、不整合があれば書き込み前に停止する。

Google Calendar同期用の依存関係:

```bash
pip install -r requirements-gcal.txt
python3 sync_gcal.py
```

用語集の運用:
- 「推察」確度はことが自動追記。内田さんが「複数一致」「公式確認」に昇格させると自動マッチングに反映。
- 初回起動時に会場マスタの全会場名を「複数一致」で自動投入（bootstrap_glossary_if_empty）。

### 定番イベントの能動検索

- `data/evergreen_events.json` に定番会場、開催月、表記ゆれ、公式URLを定義する。
- 会場マスタの `例年開催月` も自動的に検索対象へ取り込む。
- 今月から設定した先の月まで、会場名＋年でGoogle NewsとXを能動検索する。
- 公式URLを直接確認し、今年の開催情報が見つからない対象をNotionへ警告表示する。
- X検索は既存の日次・月次予算を共有し、1実行あたりの対象数にも上限を持つ。

### 必要な GitHub Secrets

| Secret | 用途 |
|---|---|
| `NOTION_API_TOKEN` | Notion インテグレーション（内部）のアクセストークン |
| `NOTION_PAGE_ID` | 書き込み先ページの ID |
| `TWITTERAPI_IO_KEY` | X(twitterapi.io) 収集用キー。**未設定なら X 収集はスキップ**（fail-safe） |
| `GLOSSARY_DB_ID` | 📖 盆踊ラー用語集 DB ID（`989e9effc7fc40db8043a3b8e03090ee`）。未設定でも fail-safe スキップ |

Notion インテグレーション `bon-odori-collector` が対象ページに共有されている必要がある。

### DynamoDB 裏取りキュー（移行中）

| 変数 | 用途 |
|---|---|
| `AWS_REGION` | AWSリージョン。既定値は `ap-northeast-1` |
| `DYNAMODB_QUEUE_TABLE` | 裏取りキューのDynamoDBテーブル名 |
| `QUEUE_STORAGE_MODE` | `notion`（既定）/ `dual` / `dynamodb` |

AWS準備後はまず `dual` でNotionとDynamoDBへ二重書きし、検証完了後に
`dynamodb` へ切り替える。GitHub ActionsのAWS認証は長期アクセスキーではなく
OIDCロールを使う。
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

### イベント発言断片パイロット

- 合意時点のスコア上位49件と `@karinchanchanko` の計50件を `data/x_event_evidence_cohort.json` に固定し、日次スコア再計算で母集団が変わらないようにする。
- 初回は対象人数を絞らず、前年同日から14日間だけ取得する。完了後は `awaiting_review` で停止し、自動的に次期間へ進めない。
- 検索語は盆踊り語に限定せず、取得後に参加予定・問い合わせ・推薦・誘い・過去参加のA〜Eを複数判定する。
- A〜Eに該当した投稿は低スコアでも1投稿1証拠として「🔎裏取りキュー」に保存する。
- 重複排除はイベント名でなく `evidence:<tweet_id>` を使う。状態は `data/x_event_evidence_state.json` に保存し、バッチとカーソル単位で再開する。
- 検知スコアは発言単体のレビュー順にのみ使い、別投稿との関連度やアカウント信頼度とは分離する。

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
