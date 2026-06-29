# 盆踊り管理コンソール設計メモ

Updated: 2026-06-26 JST  
署名: おと（Codex）

## 結論

レビューコンソールと運用メトリクスは、1つのローカル管理サービスとして統合する。

ただし、内部の責務は混ぜない。

- レビュー判断: `review_console/` が担う
- 運用メトリクス収集: `collect_ops_metrics.py` が担う
- 実データ反映: 既存の個別 apply スクリプトが担う
- Notion / Master RDB / 公開 JSON / デプロイ: 管理コンソールから直接変更しない

管理者から見ると「1つの画面」だが、実装上は「安全なローカル操作面 + 読み取り中心の運用状態表示」にする。

## 実装ステータス

- Phase 1 読み取り統合API: 実装済み
  - `review_console.data.load_admin_summary()`
  - `GET /api/admin-summary`
  - admin summary の単体テスト
- Phase 2 ホーム画面: 実装済み
  - `ホーム` / `レビュー` タブ
  - `/api/admin-summary` を使った注意カード
  - 注意カード・主要指標からレビュー絞り込みへ遷移
  - ホーム上のYouTube収集・公開補助サマリー
- Phase 3 メトリクス画面: 実装済み
  - `GET /api/ops-metrics`
  - `GET /api/ops-history`
  - `メトリクス` タブ
  - 最新値と前回差分のカード
  - YouTube候補、レビュー/正本整備、公開補助の推移グラフ
  - 履歴表

## 何が起きているか

現状は、次の2つが分かれている。

- `run_review_console.py`
  - JSON review/queue ファイルを横断して、採用・却下・保留・要調査を保存する
  - 出力は `data/review_console/decisions.json`、export、staged decision file
  - 実データは変更しない
- `collect_ops_metrics.py`
  - 日次収集、YouTube候補、公開補助情報、未整備件数などを集計する
  - 出力は `data/ops_metrics_latest.md`、`data/ops_metrics_history.jsonl`、`data/ops_metrics_dashboard.html`
  - 静的HTMLなので、レビュー操作とは分断されている

問題は、管理者が「数字を見たあと、どのレビューをすればよいか」を別々に判断する必要があること。

統合後は、トップ画面で異常や残作業を見て、そのまま該当レビューへ移動できるようにする。

## サービス名

作業名は `盆踊り管理コンソール` とする。

実行コマンドは当面 `python3 run_review_console.py` のままでよい。既存の起動手順を壊さず、画面タイトルと内部APIを広げる。

将来的にファイル名を変えるなら、互換ラッパーとして `run_review_console.py` は残す。

## 管理者の主要な問い

画面は、次の問いに短く答える。

1. 今日、詰まっているものはあるか
2. 先に見るべきレビュー対象はどれか
3. ステージ済みで、まだ個別 apply が終わっていない判断はあるか
4. YouTube収集は進んでいるか、quota停止か、対象が残っているか
5. 公開データの見え方に影響する補助情報が急変していないか
6. Master RDB側の欠損や品質課題は増えていないか

## 情報設計

### 1. ホーム

最初に開く画面。

表示するもの:

- 今日の注意
  - ステージ反映待ち
  - ステージが古い
  - 未レビューが残っている
  - missing venue / missing source URL / missing date_start
  - YouTube実行が quota 停止、または対象が残っている
- 今日やること
  - 「根拠URL不足を確認」
  - 「会場不足レビューを見る」
  - 「YouTube年次バックフィルを見る」
  - 「登録済みイベント調査を見る」
- 数字カード
  - 未レビュー
  - 決定済み
  - ステージ反映待ち
  - YouTube候補
  - review候補
  - 登録済み不完全
  - missing venue
  - missing source URL

重要なのは、各カードをクリックすると該当レビューのフィルタに移動すること。

例:

- `missing source URL` -> `source=missing_source_url`
- `missing venue` -> `source=missing_occurrence_venue`
- `登録済み不完全` -> `source=registered_event_investigation`
- `YouTube review` -> `domain=YouTube`

### 2. レビュー

既存レビューコンソールを維持する。

変える点:

- ヘッダーに `ホーム` / `レビュー` / `メトリクス` のタブを置く
- ホームから渡されたフィルタを受け取れるようにする
- 左サイドバーの件数は今のまま活かす
- `ステージ適用` は現状通り、実反映ではなく staged file 作成だけにする

### 3. メトリクス

`data/ops_metrics_dashboard.html` の内容を、同じサービス内のビューとして出す。

最初のMVPでは、次の3ブロックで十分。

- YouTube収集
  - `youtube_run_status`
  - `youtube_run_selected_rows`
  - `youtube_run_completed_batches`
  - `youtube_run_remaining_before`
  - `youtube_run_remaining_after`
  - `youtube_run_estimated_search_calls`
- 候補品質
  - `youtube_candidates_total`
  - `youtube_candidates_strong`
  - `youtube_candidates_review`
  - `youtube_candidates_weak`
- 未解決・公開補助
  - `low_confidence_review_unreviewed_rows`
  - `registered_events_incomplete`
  - `missing_venue_occurrences`
  - `missing_source_url_occurrences`
  - `missing_date_start_count`
  - `public_date_prediction_applied`
  - `public_historical_reference_applied`
  - `public_season_hint_applied`

履歴グラフは後でよい。MVPでは最新値と前回差分が見えれば運用判断に使える。

### 4. ジョブ履歴・運用リンク

第2段階以降で追加する。

- 日次YouTube
- 週次glossary
- public JSON postprocess
- Google Calendar sync
- Notion queue migration
- X/RSS collection

この画面は実行ボタンより、まず runbook と最新成果物へのリンクを並べる。
誤操作を避けるため、最初からジョブ実行UIにはしない。

## API設計

既存API:

- `GET /api/inventory`
- `GET /api/items`
- `GET /api/item/{id}`
- `GET /api/decisions`
- `GET /api/stage-status`
- `POST /api/decision`
- `POST /api/export`
- `POST /api/inventory/write`
- `POST /api/stage-apply`
- `POST /api/stage-ack`

追加するAPI:

### `GET /api/admin-summary`

ホーム用の統合サマリー。

中身:

```json
{
  "generated_at": "...",
  "review": {
    "total": 0,
    "pending": 0,
    "reviewed": 0,
    "closed": 0,
    "domains": {},
    "sources": []
  },
  "stage": {
    "status": "empty",
    "needs_attention": false,
    "decision_count": 0
  },
  "ops": {
    "snapshot_date": "2026-06-26",
    "youtube_run_status": "harvested_until_quota_limited",
    "youtube_candidates_total": 557,
    "registered_events_incomplete": 79
  },
  "attention": [
    {
      "level": "warn",
      "title": "根拠URL不足があります",
      "value": 4,
      "target": {"view": "review", "source": "missing_source_url"}
    }
  ]
}
```

実装は、`review_console.data.load_inventory()`、`review_console.data.stage_status()`、`collect_ops_metrics.collect_metrics()` を合成するだけでよい。

### `GET /api/ops-metrics`

最新メトリクスを返す。

`collect_ops_metrics.collect_metrics()` を呼ぶか、`data/ops_metrics_history.jsonl` の最新行を読む。

MVPでは「読むだけ」を優先する。
収集・HTML再生成までAPIで走らせると、画面更新ボタンの意味が重くなるため。

### `GET /api/ops-history`

履歴グラフ用。

`data/ops_metrics_history.jsonl` を読み、最新30件程度を返す。

第1段階では未実装でもよい。

## 注意判定ルール

ホームの `attention` は、最初は単純なルールでよい。

- `stage.needs_attention == true`
  - level: `danger`
  - action: 決定済みを見る / 再ステージ
- `review.pending > 0`
  - level: `warn`
  - action: 未レビューを見る
- `missing_source_url_occurrences > 0`
  - level: `warn`
  - action: 根拠URL不足を見る
- `missing_venue_occurrences > 0`
  - level: `warn`
  - action: 会場不足レビューを見る
- `missing_date_start_count > 0`
  - level: `info`
  - action: 登録済みイベント調査を見る
- `youtube_review_queue_undecided_groups > 0`
  - level: `warn`
  - action: YouTube年次バックフィルを見る
- `youtube_run_status` が `quota_limited` または `harvested_until_quota_limited`
  - level: `info`
  - action: メトリクスを見る

注意点:

- quota停止は通常運用でも起きるので、`danger` にしない
- 登録済み不完全や missing date_start は数が多い前提なので、毎回強い警告にしない
- `danger` は「今の判断を反映すると危ない」「ステージが古い」など、操作ミスに直結するものへ限定する

## 実装順序

### Phase 1: 読み取り統合API

やること:

- `review_console/data.py` に admin summary 生成関数を追加
- `review_console/server.py` に `GET /api/admin-summary` を追加
- `collect_ops_metrics.py` の既存関数を再利用
- テストで `attention` と主要メトリクスが返ることを確認

この段階ではUIを変えない。
リスクが低く、既存レビュー操作を壊しにくい。

### Phase 2: ホーム画面

やること:

- `index.html` にホーム/レビューのタブを追加
- `app.js` で `/api/admin-summary` を読み込む
- 注意カードと「今日やること」を表示
- カードクリックでレビューのフィルタを切り替える

この段階で、管理者が最初に見る画面はホームになる。

### Phase 3: メトリクス画面

やること:

- `GET /api/ops-metrics` を追加
- メトリクスビューを同じCSSで作る
- まずは最新値と前回差分のみ
- 履歴グラフは必要になってから追加

既存の `data/ops_metrics_dashboard.html` は当面残す。
統合画面が安定してから廃止判断する。

### Phase 4: 運用リンク集

やること:

- docs/runbook へのリンクを管理コンソールに集約
- 最新成果物ファイルへの相対パスを表示
- ジョブ実行ボタンはまだ置かない

### Phase 5: 実行UIの検討

条件付きで検討する。

- dry-run が明確
- 実行ログが残る
- rollback または再生成手順がある
- 既存の「本番反映は明示依頼時だけ」というルールに反しない

最初から実行UIを作らない。

## 非対象

この統合でやらないこと:

- Master RDBの直接更新
- Notionへの直接書き込み
- public JSONの本番反映
- S3同期
- CloudFront invalidation
- GitHub Actions deploy の起動
- 常駐サービス化
- 外部公開
- 認証つきWebサービス化

ローカルの `127.0.0.1` 限定を維持する。

## デザイン方針

盆踊り管理コンソールは、マーケティングサイトではなく運用ツール。

画面は派手にしない。

- 情報密度はやや高め
- カードは個別項目や注意に限定
- トップは「今日やること」が最初に見える
- ボタンは操作の意味が明確なものだけ
- レビュー画面は既存のキーボード操作を維持
- 危険な操作は色だけでなく文言で明示

カラールール:

- `danger`: 古いステージ、反映ミスに直結する状態
- `warn`: 人手レビューが必要な状態
- `info`: 通常運用上の注意、quota停止、残数
- `ok`: 詰まりなし、反映確認済み

## 成功条件

MVPの成功条件:

- 管理者が `http://127.0.0.1:8751/` を開いて、最初に今日の作業優先度を判断できる
- メトリクス上の課題から該当レビューへ1クリックで移動できる
- ステージ反映待ちや古いステージが見落とされにくい
- 既存のレビュー保存、export、stage apply の挙動が変わらない
- 既存テスト `tests.test_review_console` と `tests.test_collect_ops_metrics` が通る

## 次の具体作業

次は Phase 4 に進む。

1. docs/runbook へのリンクを管理コンソールに集約
2. 最新成果物ファイルへの相対パスを表示
3. ジョブ実行ボタンは置かず、まず運用リンク集として作る
4. 既存の `data/ops_metrics_dashboard.html` は統合画面が安定するまで残す
