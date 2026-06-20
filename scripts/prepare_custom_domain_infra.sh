#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE_NAME="${AWS_PROFILE:-bon-odori}"
AWS_REGION_NAME="${AWS_REGION:-ap-northeast-1}"
ACM_REGION_NAME="${ACM_REGION:-us-east-1}"
CLOUDFRONT_DISTRIBUTION_ID="${CLOUDFRONT_DISTRIBUTION_ID:-ERA76BJB7WLEN}"
CLOUDFRONT_ZONE_ID="${CLOUDFRONT_ZONE_ID:-Z2FDTNDATAQYW2}"
WAF_NAME="${WAF_NAME:-bonsuke-site-prod-web-acl}"
DOMAIN_NAME="${DOMAIN_NAME:-}"
WWW_DOMAIN_NAME="${WWW_DOMAIN_NAME:-}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-}"
ACM_CERT_ARN="${ACM_CERT_ARN:-}"
APPLY="${APPLY:-0}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WAF_RULES_FILE="$ROOT/infra/waf-cloudfront-managed-rules.json"

if [[ -z "$DOMAIN_NAME" ]]; then
  echo "DOMAIN_NAME is required, e.g. DOMAIN_NAME=example.jp" >&2
  exit 2
fi

run() {
  echo
  echo "+ $*"
  if [[ "$APPLY" == "1" ]]; then
    "$@"
  fi
}

say() {
  echo
  echo "## $*"
}

say "Mode"
if [[ "$APPLY" == "1" ]]; then
  echo "APPLY=1: commands will run."
else
  echo "dry-run: commands are printed only. Set APPLY=1 after review and explicit GO."
fi

say "Inputs"
echo "AWS_PROFILE=$AWS_PROFILE_NAME"
echo "AWS_REGION=$AWS_REGION_NAME"
echo "ACM_REGION=$ACM_REGION_NAME"
echo "CLOUDFRONT_DISTRIBUTION_ID=$CLOUDFRONT_DISTRIBUTION_ID"
echo "DOMAIN_NAME=$DOMAIN_NAME"
echo "WWW_DOMAIN_NAME=$WWW_DOMAIN_NAME"
echo "HOSTED_ZONE_ID=$HOSTED_ZONE_ID"
echo "ACM_CERT_ARN=$ACM_CERT_ARN"
echo "WAF_NAME=$WAF_NAME"

say "CloudFront distribution domain"
run aws cloudfront get-distribution \
  --profile "$AWS_PROFILE_NAME" \
  --id "$CLOUDFRONT_DISTRIBUTION_ID" \
  --query "Distribution.DomainName" \
  --output text

say "Request ACM certificate in us-east-1"
cert_args=(
  aws acm request-certificate
  --profile "$AWS_PROFILE_NAME"
  --region "$ACM_REGION_NAME"
  --domain-name "$DOMAIN_NAME"
  --validation-method DNS
  --idempotency-token "bonsuke$(date +%Y%m%d)"
  --query CertificateArn
  --output text
)
if [[ -n "$WWW_DOMAIN_NAME" ]]; then
  cert_args+=(--subject-alternative-names "$WWW_DOMAIN_NAME")
fi
run "${cert_args[@]}"

if [[ -n "$ACM_CERT_ARN" ]]; then
  say "Read ACM DNS validation records"
  run aws acm describe-certificate \
    --profile "$AWS_PROFILE_NAME" \
    --region "$ACM_REGION_NAME" \
    --certificate-arn "$ACM_CERT_ARN" \
    --query "Certificate.DomainValidationOptions[].ResourceRecord"

  say "Wait for ACM validation"
  run aws acm wait certificate-validated \
    --profile "$AWS_PROFILE_NAME" \
    --region "$ACM_REGION_NAME" \
    --certificate-arn "$ACM_CERT_ARN"
else
  say "Next step"
  echo "Set ACM_CERT_ARN after certificate request, add the DNS validation CNAME in Route53, then rerun."
fi

say "Prepare CloudFront alias/certificate update"
cat <<EOF
This step is intentionally manual-review first because CloudFront update-distribution
requires editing the complete distribution config.

Commands:
  aws cloudfront get-distribution-config --profile "$AWS_PROFILE_NAME" --id "$CLOUDFRONT_DISTRIBUTION_ID" > /tmp/bonsuke-distribution-config.json
  jq ... /tmp/bonsuke-distribution-config.json > /tmp/bonsuke-distribution-config-updated.json
  aws cloudfront update-distribution --profile "$AWS_PROFILE_NAME" --id "$CLOUDFRONT_DISTRIBUTION_ID" --if-match "\$(jq -r '.ETag' /tmp/bonsuke-distribution-config.json)" --distribution-config file:///tmp/bonsuke-distribution-config-updated.json

See docs/aws-custom-domain-runbook.md for the full jq expression.
EOF

say "Create WAF WebACL"
run aws wafv2 create-web-acl \
  --profile "$AWS_PROFILE_NAME" \
  --region "$ACM_REGION_NAME" \
  --scope CLOUDFRONT \
  --name "$WAF_NAME" \
  --default-action Allow={} \
  --visibility-config "SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=bonsukeSiteProdWebAcl" \
  --rules "file://$WAF_RULES_FILE"

say "Associate WAF WebACL"
cat <<EOF
Commands:
  ACCOUNT_ID=\$(aws sts get-caller-identity --profile "$AWS_PROFILE_NAME" --query Account --output text)
  WEB_ACL_ARN=\$(aws wafv2 list-web-acls --profile "$AWS_PROFILE_NAME" --region "$ACM_REGION_NAME" --scope CLOUDFRONT --query "WebACLs[?Name=='$WAF_NAME'].ARN | [0]" --output text)
  aws wafv2 associate-web-acl --profile "$AWS_PROFILE_NAME" --region "$ACM_REGION_NAME" --web-acl-arn "\$WEB_ACL_ARN" --resource-arn "arn:aws:cloudfront::\$ACCOUNT_ID:distribution/$CLOUDFRONT_DISTRIBUTION_ID"
EOF

if [[ -n "$HOSTED_ZONE_ID" ]]; then
  say "Prepare Route53 ALIAS records"
  alias_names=("$DOMAIN_NAME")
  if [[ -n "$WWW_DOMAIN_NAME" ]]; then
    alias_names+=("$WWW_DOMAIN_NAME")
  fi
  echo "Create A and AAAA ALIAS records for:"
  printf "  - %s\n" "${alias_names[@]}"
  echo "Alias target: CloudFront distribution domain from get-distribution"
  echo "Alias hosted zone id: $CLOUDFRONT_ZONE_ID"
  echo "See docs/aws-custom-domain-runbook.md for the change-resource-record-sets batch."
else
  say "Route53 ALIAS skipped"
  echo "Set HOSTED_ZONE_ID after creating/delegating the Route53 public hosted zone."
fi
