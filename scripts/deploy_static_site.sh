#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-/Users/ryotauchida/bon-odori-site-public-snapshot}"
STACK_NAME="${STACK_NAME:-bonsuke-site-prod}"
BUCKET_NAME="${BUCKET_NAME:-bonsuke-site-prod}"
AWS_PROFILE_NAME="${AWS_PROFILE:-bon-odori}"
AWS_REGION_NAME="${AWS_REGION:-ap-northeast-1}"
TEMPLATE="$ROOT/infra/static-site.yml"

if [[ ! -d "$SNAPSHOT_DIR" ]]; then
  echo "snapshot directory not found: $SNAPSHOT_DIR" >&2
  exit 1
fi

if [[ ! -f "$SNAPSHOT_DIR/index.html" ]]; then
  echo "snapshot is missing index.html: $SNAPSHOT_DIR" >&2
  exit 1
fi

echo "[deploy] profile=$AWS_PROFILE_NAME region=$AWS_REGION_NAME stack=$STACK_NAME bucket=$BUCKET_NAME"
echo "[deploy] snapshot=$SNAPSHOT_DIR"

aws cloudformation deploy \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE" \
  --parameter-overrides "BucketName=$BUCKET_NAME" \
  --no-fail-on-empty-changeset

aws s3 sync "$SNAPSHOT_DIR/" "s3://$BUCKET_NAME/" \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --delete \
  --exclude ".git/*" \
  --exclude ".DS_Store" \
  --exclude "*/.DS_Store" \
  --exclude "._*" \
  --exclude "*/._*"

DISTRIBUTION_ID="$(aws cloudformation describe-stacks \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue | [0]" \
  --output text)"

SITE_URL="$(aws cloudformation describe-stacks \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='SiteUrl'].OutputValue | [0]" \
  --output text)"

aws cloudfront create-invalidation \
  --profile "$AWS_PROFILE_NAME" \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*" >/dev/null

echo "[deploy] distribution_id=$DISTRIBUTION_ID"
echo "[deploy] site_url=$SITE_URL"
