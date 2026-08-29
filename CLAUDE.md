# bon-odori-collector

盆踊り関連ニュース、X由来の声、公式サイト監視、YouTube由来の過去実績を収集し、Master RDB / DynamoDB / 公開サイト用JSONへ流す仕組み。

Notion はイベント公開・キュー運用の正本ではない。現在の境界は `docs/notion-usage-policy.md` を優先する。

## 仕様書 docs/spec/ を同時に更新する（2026-08-13 内田さん指示）

このリポジトリには階層型の仕様書 `docs/spec/` がある。L0（全体地図）→ L1（サブシステム7本）→
L2（データ契約）→ ソース、という4層で、「どこを触ると何が壊れるか」を書き留めてある。

**コードやデータの流れを追加・修正・削除したときは、同じPRの中で `docs/spec/` も直す。**
別PRにしない。後回しにすると必ず忘れられ、仕様書が飾りになる。

- 作業を**始める前**に `python3 scripts/spec_index.py impact --files <path>...` を引き、
  触るファイルがどの仕様に属し、どの不変条件（INV-xxx）に関わるのかを確認する。
- 挙動を変えたら、その仕様の本文と front matter の `updated_for` を更新する。
- 守るべき約束が増えた・変わった・不要になったなら `### INV-xxx` を追加・修正・廃止する。
  新しい不変条件には、それを守るテストを名指しする。無いなら `**なし（要追加）**` と正直に書く。
- **ファイルを消す・移動する・分割するときは `owns` を必ず直し、その場で `impact` を引いて確認する。**
  2026-08-13 に `master_rdb/s3_artifact.py` が `owns` から抜け落ち、
  スキーマ退行事故の再発防止が書かれたファイルを触っても警告が出ない状態になった。
- 書き方の正本は `docs/spec/SPEC-GUIDE.md`。**仕様書を書き足す前に必ず読む。**
- HTML閲覧版は `python3 scripts/spec_html.py --out <path>.html` で生成する。手書きしない。

### 仕様書と実態がずれていたら、見つけた時点で直す

ずれることは前提として織り込む。**ずれていること自体は失敗ではない。見つけたのに直さず素通りすることが失敗である。**

- 作業中に「記述が実態と違う」と気づいたら、その場で直す。別タスクに切り出さず、確認も求めなくてよい。
- 直すのは気づいた範囲だけでよい。周辺を全部点検し直す必要はない。
- 実装を読んでも正解が分からない場合は、推測で書き換えない。「未確認」と明記して残す。
  **間違った記述より、確認していないと分かる記述のほうがよい。**
- 事故の原因が判明したときは、症状と不変条件を必ず追記する。一度壊れた箇所はまた壊れる。

## 構成

- `collect.py` - RSS/X/公式監視向けの収集入口。Notionページ投稿は `NOTION_PAGE_ID` を明示した時だけのレガシー出力。
- `.github/workflows/collect.yml` - 毎日 15:13 JST（cron `13 6 * * *`）+ 手動実行で収集、公式監視、公開JSON再生成を行う。
- `export_public_events.py` - Master RDB から公開サイト用JSONを生成する。Notion経路は `BON_ODORI_PUBLIC_SOURCE=notion` 指定時だけの手動フォールバック。
- `bon_odori_songs.py` - イベント説明・開催実績から、会場で踊られる曲目ヒントを保守的に抽出。
- `build_event_song_candidates.py` - X・ニュース・東京盆踊りマップ由来メモから曲目候補を広めに集め、レビュー用JSONへ保存。
- `send_mail.py` - `data/pending_mail.json` を Gmail SMTP で送信する日刊メール配信。

## 動作の要点

- `latest.json` は「現在取得できた記事の全件スナップショット」。差分（新着のみ）ではない。
- `seen.json` は履歴として累積し続ける。
- 日次収集では、Master RDB artifact を取得してから収集・公式監視・公開JSON再生成を行う。
- 公開JSONは `data/public/events_public.json` に出力する。
- `bon-odori-site` 側の `Sync public data` workflow が collector の公開JSONを取り込み、差分がある時だけ公開デプロイする。
- 曲目ヒントは `events_public.json` の各イベント内 `songs` と、確認用の `data/public/event_songs_public.json` に出力する。
- 公開前レビュー用の曲目候補は `data/event_song_candidates.json` に出力する。これは広めに拾うため、確認後にRDB/曲マスタ側へ反映する。

## Notion 境界

- 公開イベントの正本: Master RDB。
- 公開サイトの入力: `data/public/events_public.json`。
- 裏取り/イベント候補キューの既定保存先: DynamoDB。
- NotionイベントDBは、移行前データの参照・過去ログ・明示的な手動フォールバックとして扱う。
- `collect.py` のNotionページ投稿は `NOTION_API_TOKEN` と `NOTION_PAGE_ID` を両方設定した場合だけ実行される。通常のGitHub Actionsでは `NOTION_PAGE_ID` を渡さない。
- 新規コードは、イベント公開やキュー運用でNotionを既定値にしない。

### 残っているNotion-backed用途

| 用途 | 位置づけ |
|---|---|
| 用語集・曲マスタ・週次コスト | 既存の明示的なNotion-backed workflowとして残す |
| Xメンバーリスト | 手動承認済み候補だけを同期する任意workflow |
| Notion snapshot | 移行検証用の読み取り専用参照 |
| `BON_ODORI_PUBLIC_SOURCE=notion` | 障害時の手動フォールバック。通常運用では使わない |

## GitHub Secrets / Variables

| Secret | 用途 |
|---|---|
| `NOTION_API_TOKEN` | Notion-backed の用語集・曲・コスト・手動レビュー用途。公開イベント生成には不要 |
| `TWITTERAPI_IO_KEY` | X(twitterapi.io) 収集用キー。未設定なら X 収集はスキップ |
| `GLOSSARY_DB_ID` | 盆踊ラー用語集 DB ID。未設定でも fail-safe スキップ |

`NOTION_PAGE_ID` は通常運用では使わない。明示的に収集サマリーをNotionページへ投稿したい時だけ設定する。

| Variable | 用途 |
|---|---|
| `AWS_ROLE_ARN` | GitHub Actions OIDC role |
| `DYNAMODB_QUEUE_TABLE` | 裏取りキューのDynamoDBテーブル名 |
| `EVENT_CANDIDATE_QUEUE_TABLE` | イベント候補v2キューのDynamoDBテーブル名 |
| `MASTER_DB_S3_BUCKET` | Master RDB artifact bucket |
| `MASTER_DB_S3_PREFIX` | Master RDB artifact prefix |
| `QUEUE_STORAGE_MODE` | `dynamodb`（既定）/ `dual` / `notion` |
| `EVENT_QUEUE_STORAGE_MODE` | イベント候補v2キューの保存先。未設定なら `QUEUE_STORAGE_MODE` に従う |

GitHub ActionsのAWS認証は長期アクセスキーではなくOIDCロールを使う。

## メール配信

- 配信本文は `data/pending_mail.json` に置く。
- `send_mail.yml` は設定と本文を事前検査し、`pending_mail.json` を `sending_mail.json` へ移してcommit・pushしてから送信する。
- `send_mail.py` はclaim済みの `sending_mail.json` だけを送信し、送信成功後にworkflowが削除をcommit・pushする。
- `pending_mail.json` が存在するのに設定不足・本文空などで送信できない場合は非ゼロ終了し、pendingのまま残す。
- `sending_mail.json` が残った場合はSMTP成否が曖昧なので自動再送しない。Gmailの送信済みを確認して人が解消する。
- 宛先はGitHub Secret `MAIL_TO` だけから読み、コード内の既定宛先は持たない。

## X(twitterapi.io) 収集

- 設定は `x_queries.json` に外出しする。
- 除外語ヒットはノイズ、体験語ヒットは一次レポ、それ以外は関心として自動仕分けする。ノイズは `voices.json` に流さない。
- 旧設計では Notion「X収集ログ DB」へ全件記録していた。現在の通常運用では、公開・キュー・RDB更新の既定経路には使わない。
- 予算上限（日次/月次）、429ウェイト、例外を他収集に波及させない fail-safe を持つ。

### Xメンバーリスト

- 収集対象アカウントの正本はローカル。`data/x_collection_roster.json`（Notionからの移行分）＋ `data/x_important_informants.json`（手動の重要情報提供者）＋ `data/x_official_source_accounts.json`（公式）＋ スコア台帳の `trusted` 自動編入。Notion「Xメンバーリスト」は任意フォールバックで、読めなくても収集は成立する。
- `data/x_account_scores.json` はアカウント価値のローカル/Actions成果物として扱う。自動編入の条件は `x_queries.json` の `auto_trusted_roster`。
- Notion「X メンバーリスト」への追加・同期は、内田さんが保存済みレビュー結果に `user_approved: true` または `registration_decision: approved/登録/追加` を付けた候補だけに限定する。`apply_x_roster_decisions.py` はNotionへ書き込まない。
- 保存済み結果だけ再同期する場合は `.github/workflows/review_x_candidate_posts.yml` の `sync_only=true` を使う（X API課金なし）。
- 誰を読んでいるかはレビューコンソールの「X情報源アカウント一覧」で確認・変更する。運用の詳細は `docs/x-collection-operations.md`。

### ポスター画像の読み取り

- `build_event_poster_ocr_queue.py` が作るキューは、開催日が未確定のイベントに触れている投稿を先頭に並べる。
- 画像の取得は `fetch_poster_images.py`、読み取りはこと（Claude Code）が Read で行う。読んだ内容の master RDB 反映は掲示物レポート経路（`docs/official-notice-field-report-operations.md`）を使う。
- 読み取り済みの記録は `data/poster_ocr_processed.json`。キューは毎日作り直されるため、この台帳が「読んだかどうか」の正本。

## この仕組みの思想

Claude が動いていなくても GitHub Actions が自律実行し、RDB・DynamoDB・公開サイトが更新される。
スケジュール実行のたびに Claude が動く Cowork とは役割が異なる。
