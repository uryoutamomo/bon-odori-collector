# voices.json のS3正本運用

`data/voices.json` はX・YouTube・RSS等の本文を含む全ソースの作業コピーであり、Gitには保存しない。正本は専用・非公開の Voices archive S3 bucket に置く。各プログラムは従来どおりローカルの `data/voices.json` を読むため、読取りconsumerをS3 APIへ個別移行する必要はない。

## 必ず守る初回移行順序

**① CloudFormation更新 → ② PRブランチでseed → ③GitHub Actions variables設定 → ④PR merge** の順で実施する。seed前にmergeすると、追跡から外れた `data/voices.json` を日次workflowが復元できない。

1. AWS認証済み端末でスタックを更新する。

```bash
aws cloudformation deploy \
  --stack-name bon-odori-dynamodb \
  --template-file infra/dynamodb-queue.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides VoicesArchiveBucketName=bon-odori-voices-169805602203
```

2. このPRブランチで、Git追跡中の既存ファイルを一回だけseedする。`seed` は既存artifactがあれば拒否し、データを書き換えない。

```bash
VOICES_S3_BUCKET=bon-odori-voices-169805602203 \
VOICES_S3_PREFIX=voices \
AWS_REGION=ap-northeast-1 \
python voices_s3_artifact.py seed \
  --snapshot-id initial-git-snapshot \
  --expect-source-sha256 "$(shasum -a 256 data/voices.json | awk '{print $1}')" \
  --expect-item-count 30662
```

3. seedの出力checksum・件数をseed元と照合し、GitHub repository variablesへ設定する。

- `VOICES_S3_BUCKET`: CloudFormation output `VoicesArchiveS3BucketName`
- `VOICES_S3_PREFIX`: output `VoicesArchiveS3Prefix`（既定 `voices`）

4. このPRをmergeする。日次workflowはAWS認証直後に `fetch --overwrite` し、全処理後・Git commit前に `publish` する。

## 手動で本文を更新するコマンド

`collect.py`、YouTube refresh、2025 backfill、YouTube description backfillのいずれも、標準パスの書込み前にS3 provenanceを検証する。先にfetchしていない `data/voices.json` は書込みを拒否する。

手動実行では共通wrapperを使う。

```bash
VOICES_S3_BUCKET=bon-odori-voices-169805602203 \
python voices_s3_artifact.py run -- python refresh_youtube_voices.py
```

このwrapperは fetch → 対象コマンド → publish の順で実行する。publish時はfetch時のchecksumとS3 latestを照合し、別のwriterが先に更新していれば停止する。日次workflowは既存concurrencyで直列化されている。

## 保持と安全性

- Voices archiveはraw X archiveとは別バケット。rawは判定前のX投稿で180日保持、voicesは判定後の全ソースで無期限保持。
- バケットはBlock Public Access、Bucket owner enforced、SSE-S3 (AES256)、HTTPS以外の拒否を適用する。
- GitHub Actionsロールにはこのバケットの専用prefixに対する `GetObject` / `PutObject` だけを付与する。
- 既存のGit履歴はこの移行では書き換えない。履歴削除（force-pushを伴う）は、稼働確認後に別途の明示承認で扱う。
