# X 生投稿アーカイブ運用

X API から初めて取得した投稿は、意味判定・`voices_seen.json` 更新より前に、専用の非公開 S3 バケットへ gzip 圧縮 JSONL と manifest を保存する。
`text` は `voices.json` の 500 文字上限を適用しない原文、`media_urls`、投稿 ID、URL、API payload の SHA-256、取得経路・検索バッチ・取得時刻を含む。判定・要約・ランキングはこの保存処理に含めない。

## 初回設定 / スタック更新

この変更を main に入れる前後で、AWS 認証済みの端末から既存スタックを更新する。これにより専用バケット、TLS 強制ポリシー、GitHub Actions OIDC ロールの `PutObject` 権限が作成される。

```bash
aws cloudformation deploy \
  --stack-name bon-odori-dynamodb \
  --template-file infra/dynamodb-queue.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides RawXPostsBucketName=bon-odori-x-raw-posts-169805602203
```

スタック名やバケット名を別にしている環境では、その値に合わせる。完了後は出力を確認する。

```bash
aws cloudformation describe-stacks \
  --stack-name bon-odori-dynamodb \
  --query "Stacks[0].Outputs[?OutputKey=='RawXPostsS3BucketName'||OutputKey=='RawXPostsS3Prefix']" \
  --output table
```

GitHub リポジトリ `uryoutamomo/bon-odori-collector` の Actions variables に次を設定する。

- `X_RAW_POSTS_S3_BUCKET`: `RawXPostsS3BucketName` の値（必須）
- `X_RAW_POSTS_S3_PREFIX`: `RawXPostsS3Prefix` の値（任意。既定は `x-raw`）

既存の `AWS_ROLE_ARN` は CloudFormation 出力 `GitHubActionsRoleArn` のロールを指す必要がある。

## 保持・安全性

- S3 Block Public Access、Bucket owner enforced、SSE-S3 (AES256)、HTTPS 以外の全アクセス拒否。
- `x-raw/` 以下の現行オブジェクトは 180 日で削除する。非現行バージョンは 30 日、未完了マルチパートアップロードは 7 日で削除する。
- GitHub Actions はそのプレフィックスへの `s3:PutObject` とバケット所在地確認だけを持つ。読み取り・公開権限は与えない。
- 保存が一つでも失敗した場合、収集コマンドは非ゼロ終了する。`voices_seen.json` の書き込みと後続の収集結果コミットは行われない。
