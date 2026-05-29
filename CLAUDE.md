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

Notion インテグレーション `bon-odori-collector` が対象ページに共有されている必要がある。
トークン未設定時は書き込みをスキップして収集だけ行う（クラッシュしない）。

## この仕組みの思想

Claude が動いていなくても GitHub Actions が自律実行し、Notion が更新され続ける。
スケジュール実行のたびに Claude が動く Cowork とは役割が異なる。
