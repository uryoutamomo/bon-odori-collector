# DynamoDB移行 初期構築記録

日付: 2026-06-07

## 目的

会場裏取りキューなどの裏方データをNotionから外部DBへ段階的に移行する。
第一弾として、NotionとAmazon DynamoDBの並行稼働を開始した。

## AWS初期設定

- AWS無料プランでアカウントを開設
- ルートユーザーにパスキーMFAを設定
- Zero Spend Budget通知を設定
- 利用リージョンを東京 `ap-northeast-1` に統一
- 長期アクセスキーは作成していない

## 構築したリソース

CloudFormationスタック `bon-odori-dynamodb` で以下を作成した。

- DynamoDBテーブル `bon-odori-torimochi-queue`
- GitHub Actions用OIDCプロバイダー
- GitHub Actions用IAMロール
- 対象テーブルだけを操作できる最小権限ポリシー

テンプレート: `infra/dynamodb-queue.yml`

## GitHub Actions設定

Repository Variables:

- `AWS_ROLE_ARN`: CloudFormationが出力したIAMロールARN
- `DYNAMODB_QUEUE_TABLE`: `bon-odori-torimochi-queue`
- `QUEUE_STORAGE_MODE`: `dual`

OIDCによる短期認証を使用し、固定のAWSアクセスキーは保存していない。
IAMロールは対象リポジトリの`main`ブランチからのみ引き受け可能。

## コード変更

- `queue_store.py` にDynamoDBストレージ層を追加
- 会場名を正規化したハッシュキーで重複登録を防止
- Notionへの同期済み状態をDynamoDBに記録
- `dual` モードではNotionとDynamoDBへ二重書き
- Notionで「該当なし」になった候補をDynamoDBへ状態同期
- AWS設定がない環境では従来のNotion動作を維持

## 検証結果

- ローカル単体テスト: 4件成功
- Python構文検査: 成功
- GitHub Actions実環境テスト: 成功
- OIDCによるAWSロール引き受け: 成功
- 実行時に候補2件をNotionとDynamoDBへ並行保存
- 掃除ループ: エラーなし

GitHub Actions Run ID: `27080480009`

## 現在の運用

DynamoDB単独運用には切り替えず、`QUEUE_STORAGE_MODE=dual` で並行稼働する。
Notionは、こわが確認・判定する運用画面として当面維持する。

## 次回作業

- 数回の定期実行で重複・欠落・状態同期を確認
- 既存NotionキューのDynamoDB移行方法を決定
- 安定確認後、DynamoDBを正本にするか判断
- AWS無料プランの期限・クレジット残高を継続確認

記録: おと（Codex）
