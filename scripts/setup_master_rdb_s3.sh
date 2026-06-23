#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${STACK_NAME:-bon-odori-dynamodb}"
REGION="${AWS_REGION:-ap-northeast-1}"
BUCKET_NAME="${MASTER_DB_S3_BUCKET:-bon-odori-master-rdb-169805602203}"
PREFIX="${MASTER_DB_S3_PREFIX:-master-rdb}"
TEMPLATE_FILE="${TEMPLATE_FILE:-infra/dynamodb-queue.yml}"

echo "[master-rdb-s3] checking AWS credentials"
aws sts get-caller-identity --region "$REGION" >/dev/null

echo "[master-rdb-s3] deploying CloudFormation stack: $STACK_NAME"
aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE_FILE" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    MasterRdbBucketName="$BUCKET_NAME" \
    MasterRdbPrefix="$PREFIX"

echo "[master-rdb-s3] reading stack outputs"
OUTPUTS_JSON="$(aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output json)"

OUTPUT_BUCKET="$(python3 -c 'import json,sys
outputs = {item["OutputKey"]: item["OutputValue"] for item in json.load(sys.stdin)}
print(outputs["MasterRdbS3BucketName"])' <<<"$OUTPUTS_JSON")"
OUTPUT_PREFIX="$(python3 -c 'import json,sys
outputs = {item["OutputKey"]: item["OutputValue"] for item in json.load(sys.stdin)}
print(outputs["MasterRdbS3Prefix"])' <<<"$OUTPUTS_JSON")"

echo "[master-rdb-s3] starting bootstrap workflow"
gh workflow run bootstrap_master_rdb_s3.yml \
  -f bucket="$OUTPUT_BUCKET" \
  -f prefix="$OUTPUT_PREFIX"

echo "[master-rdb-s3] waiting for bootstrap workflow run"
sleep 8
RUN_ID="$(gh run list \
  --workflow bootstrap_master_rdb_s3.yml \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')"

if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "null" ]; then
  echo "[master-rdb-s3] could not find bootstrap workflow run" >&2
  exit 1
fi

gh run watch "$RUN_ID" --exit-status

echo "[master-rdb-s3] enabling collect workflow variables"
gh variable set MASTER_DB_S3_BUCKET --body "$OUTPUT_BUCKET"
gh variable set MASTER_DB_S3_PREFIX --body "$OUTPUT_PREFIX"

echo "[master-rdb-s3] done"
echo "MASTER_DB_S3_BUCKET=$OUTPUT_BUCKET"
echo "MASTER_DB_S3_PREFIX=$OUTPUT_PREFIX"
