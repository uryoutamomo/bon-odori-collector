# AWS DynamoDB 導入手順

対象: 盆踊りプロジェクトの「裏取りキュー」

## 方針

- リージョン: 東京 `ap-northeast-1`
- 課金方式: オンデマンド
- 保存時暗号化: DynamoDB標準の暗号化を有効化
- GitHub Actions認証: OIDCによる短期認証
- 長期アクセスキーは作成・保管しない
- 現行運用: `QUEUE_STORAGE_MODE=dynamodb`
- `dual` / `notion` は移行検証・復旧時の明示指定だけに使う

## フェーズ1: 内田さんが行う初期設定

### 1. AWSアカウントを作成

1. <https://portal.aws.amazon.com/billing/signup> を開く。
2. 受信可能な専用メールアドレスとアカウント名を入力する。
3. 強いパスワード、連絡先、支払い方法、本人確認を登録する。
4. サポートプランは、特別な要件がなければ無料のBasic Supportを選ぶ。
5. アカウント有効化メールが届くまで待つ。

ルートユーザーは全権限を持つため、日常作業には使わない。

### 2. ルートユーザーにMFAを設定

1. ルートユーザーでAWS Management Consoleへサインインする。
2. 右上のアカウント名から `Security credentials` を開く。
3. `Multi-factor authentication (MFA)` でMFAを割り当てる。
4. 利用可能ならパスキーまたはセキュリティキーを優先する。
5. 復旧用メールアドレスと電話番号が最新か確認する。

### 3. 予算通知を設定

1. `Billing and Cost Management` を開く。
2. `Budgets`、`Create budget` を選ぶ。
3. `Use a template` から `Zero spend budget` を選ぶ。
4. 通知を受け取るメールアドレスを登録する。

予算通知は利用停止機能ではなく、超過を知らせる仕組み。
無料プランでは、有料プランへ変更しない限り利用料金は請求されない。

## フェーズ2: 管理者アクセス

日常管理にはルートユーザーを使わず、AWS IAM Identity Centerの管理者を作成する。
この設定はアカウント開設とMFA完了後に実施する。

## フェーズ3: DynamoDBとGitHub OIDC

CloudFormationで次をまとめて作成する。

- DynamoDBテーブル `bon-odori-torimochi-queue`
- DynamoDBテーブル `bon-odori-event-candidate-queue`
- S3バケット `bon-odori-master-rdb-169805602203`
- GitHub OIDCプロバイダー
- 対象リポジトリの`main`ブランチだけが引き受けられるIAMロール
- 対象テーブルとmaster RDB artifactだけを操作できる最小権限ポリシー

テンプレート: `infra/dynamodb-queue.yml`

作成後、CloudFormationの出力値をGitHub Actions Variablesへ登録する。

| GitHub Variable | 値 |
|---|---|
| `AWS_ROLE_ARN` | `GitHubActionsRoleArn` の出力 |
| `DYNAMODB_QUEUE_TABLE` | `QueueTableName` の出力 |
| `EVENT_CANDIDATE_QUEUE_TABLE` | `EventCandidateQueueTableName` の出力 |
| `MASTER_DB_S3_BUCKET` | `MasterRdbS3BucketName` の出力 |
| `MASTER_DB_S3_PREFIX` | `MasterRdbS3Prefix` の出力 |
| `QUEUE_STORAGE_MODE` | 通常は `dynamodb` |
| `EVENT_QUEUE_STORAGE_MODE` | 通常は `dynamodb` |

`MASTER_DB_S3_BUCKET` は、初回 artifact publish が成功してから登録する。
先に登録すると、日次 collect workflow が存在しないS3 artifactを取りに行って失敗する。

## フェーズ4: 切り替え（完了済み）

1. GitHub Actionsを手動実行する。
2. 移行対象だった旧Notionキュー行とDynamoDBの追加内容を照合する。
3. 数回の定期実行で重複・欠落がないことを確認する。
4. 既存データ移行後に `QUEUE_STORAGE_MODE=dynamodb` へ変更する。

2026-06-23時点で、daily collect のキュー保存先はDynamoDBへ切り替え済み。
Notionキューを操作画面として同期し続ける前提は終了した。

## Legacy Notion queue migration

`migrate_notion_queue_to_dynamodb.yml` は過去Notionキュー行をDynamoDBへ
移すための legacy one-off workflow。

通常運用では実行しない。必要時はまず `apply=false` のdry-runで対象を確認する。
実反映は `apply=true` と確認文字列
`MIGRATE NOTION QUEUE TO DYNAMODB` が両方ある場合だけ。

詳しい扱いは `docs/notion-queue-migration-operations.md` を正とする。
