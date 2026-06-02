# bon-odori-collector

盆踊り関連ニュースを Google News RSS から収集し、結果を Notion ページへ自動反映する仕組み。

## 構成

- `collect.py` — RSS 収集 + Notion 書き込み（標準ライブラリのみ、依存追加なし）
- `.github/workflows/collect.yml` — 毎日 15:00 JST（cron `0 6 * * *`）+ 手動実行で `collect.py` を実行
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

## X(twitterapi.io) 収集（「人の言葉」）

X API 廃止で止まっていた参加レポ・感想の収集を、非公式プロキシ **twitterapi.io**（$0.15/1000件のプリペイド）で復活させたもの。`collect.py` の `collect_x_voices()` が担当。

- **設定は `x_queries.json` に外出し**（クエリ・除外語・体験語・予算）。コードを触らず実験できる。
- **自動仕分け**: 除外語ヒット→🔴ノイズ／体験語ヒット→🟢一次レポ／それ以外→🟡関心。ノイズは `voices.json` に流さない。
- **全件を Notion「🐦 X収集ログ DB」(`ef2f627d-…`) に1行ずつ記録**。`正解ラベル`(👍/👎/未評価) を手で付けて除外語を育てる改善ループ用。
- **安全装置**: 予算上限（日次/月次, `data/x_budget.json` に消費を累積記録しコミットして実行をまたいで効かせる）・429ウェイト・例外を他収集に波及させない fail-safe。
- 設計の詳細は Notion「盆踊り情報開発 >『X収集 改善ループ 設計アイデア』」。
- `experiment_x_voices.py` は本番統合前の使い捨て実証スクリプト（記録として残置）。

## この仕組みの思想

Claude が動いていなくても GitHub Actions が自律実行し、Notion が更新され続ける。
スケジュール実行のたびに Claude が動く Cowork とは役割が異なる。
