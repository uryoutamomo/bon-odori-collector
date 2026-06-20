# Bonsuke custom domain infrastructure runbook

Last updated: 2026-06-19

This is a pre-flight runbook for attaching a future Sakura-registered custom
domain to the existing Bonsuke CloudFront distribution.

No Web deployment should be run from this procedure. S3 sync and CloudFront
invalidation remain gated by the normal explicit GO rule.

## Current fixed values

- AWS profile: `bon-odori`
- Main AWS region: `ap-northeast-1`
- CloudFront / ACM for viewer certificate region: `us-east-1`
- CloudFront distribution ID: `ERA76BJB7WLEN`
- CloudFront hosted zone ID for Route53 ALIAS: `Z2FDTNDATAQYW2`
- Existing static site stack: `bonsuke-site-prod`

## Values to fill after domain purchase

- `DOMAIN_NAME`: apex domain, for example `example.jp`
- `WWW_DOMAIN_NAME`: optional `www.example.jp`
- `HOSTED_ZONE_ID`: Route53 public hosted zone ID for `DOMAIN_NAME`
- `ACM_CERT_ARN`: ACM certificate ARN in `us-east-1` after validation
- `WAF_NAME`: default `bonsuke-site-prod-web-acl`

## Important DNS prerequisite

Route53 ALIAS records only work in a Route53 hosted zone that is authoritative
for the domain. After Sakura registration, choose one of these:

1. Create a Route53 public hosted zone for the domain and copy its NS records
   into Sakura's domain DNS settings. This is recommended for ALIAS.
2. Keep Sakura DNS and use a CNAME only for `www`. An apex ALIAS to CloudFront
   is not available in Sakura DNS unless Sakura provides equivalent flattening.

For an apex site, use option 1.

DNS delegation propagation usually takes 10 minutes to 24 hours. ACM DNS
validation is often 5 to 30 minutes after the validation CNAME is visible.

## Recommended execution order

1. Create or confirm Route53 public hosted zone.
2. Request ACM certificate in `us-east-1` for apex and optional `www`.
3. Add ACM DNS validation CNAME record(s) to Route53.
4. Wait until ACM status becomes `ISSUED`.
5. Add CloudFront alternate domain names and the ACM certificate to
   distribution `ERA76BJB7WLEN`.
6. Create and associate WAF WebACL for CloudFront.
7. Create Route53 A/AAAA ALIAS records to the CloudFront distribution.
8. Verify `https://DOMAIN_NAME/` and optional `https://www.DOMAIN_NAME/`.

## Dry-run helper

The helper prints the AWS CLI actions and can execute them only when
`APPLY=1` is set.

```bash
cd /Users/ryotauchida/bon-odori-collector
DOMAIN_NAME=example.jp \
WWW_DOMAIN_NAME=www.example.jp \
HOSTED_ZONE_ID=ZXXXXXXXXXXXXX \
./scripts/prepare_custom_domain_infra.sh
```

After review and explicit GO:

```bash
APPLY=1 \
DOMAIN_NAME=example.jp \
WWW_DOMAIN_NAME=www.example.jp \
HOSTED_ZONE_ID=ZXXXXXXXXXXXXX \
./scripts/prepare_custom_domain_infra.sh
```

The first apply run requests the ACM certificate and prints the validation
record lookup command. After ACM is `ISSUED`, rerun with `ACM_CERT_ARN` set to
prepare CloudFront, WAF, and Route53 records:

```bash
APPLY=1 \
DOMAIN_NAME=example.jp \
WWW_DOMAIN_NAME=www.example.jp \
HOSTED_ZONE_ID=ZXXXXXXXXXXXXX \
ACM_CERT_ARN=arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
./scripts/prepare_custom_domain_infra.sh
```

## Manual command details

Confirm the existing distribution domain:

```bash
aws cloudfront get-distribution \
  --profile bon-odori \
  --id ERA76BJB7WLEN \
  --query 'Distribution.DomainName' \
  --output text
```

Request ACM certificate in `us-east-1`:

```bash
aws acm request-certificate \
  --profile bon-odori \
  --region us-east-1 \
  --domain-name "$DOMAIN_NAME" \
  --subject-alternative-names "$WWW_DOMAIN_NAME" \
  --validation-method DNS \
  --idempotency-token bonsuke$(date +%Y%m%d) \
  --query CertificateArn \
  --output text
```

Get ACM DNS validation records:

```bash
aws acm describe-certificate \
  --profile bon-odori \
  --region us-east-1 \
  --certificate-arn "$ACM_CERT_ARN" \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord'
```

Add the returned CNAME records in Route53. Then wait:

```bash
aws acm wait certificate-validated \
  --profile bon-odori \
  --region us-east-1 \
  --certificate-arn "$ACM_CERT_ARN"
```

Update CloudFront distribution aliases and certificate. This uses `jq`; review
the generated config before applying:

```bash
aws cloudfront get-distribution-config \
  --profile bon-odori \
  --id ERA76BJB7WLEN \
  > /tmp/bonsuke-distribution-config.json

jq --arg apex "$DOMAIN_NAME" \
   --arg www "$WWW_DOMAIN_NAME" \
   --arg cert "$ACM_CERT_ARN" \
   '.DistributionConfig
    | .Aliases = {Quantity: (if $www == "" then 1 else 2 end), Items: ([ $apex ] + (if $www == "" then [] else [ $www ] end))}
    | .ViewerCertificate = {
        ACMCertificateArn: $cert,
        SSLSupportMethod: "sni-only",
        MinimumProtocolVersion: "TLSv1.2_2021",
        Certificate: $cert,
        CertificateSource: "acm"
      }' \
  /tmp/bonsuke-distribution-config.json \
  > /tmp/bonsuke-distribution-config-updated.json

aws cloudfront update-distribution \
  --profile bon-odori \
  --id ERA76BJB7WLEN \
  --if-match "$(jq -r '.ETag' /tmp/bonsuke-distribution-config.json)" \
  --distribution-config file:///tmp/bonsuke-distribution-config-updated.json
```

Create WAF WebACL for CloudFront:

```bash
aws wafv2 create-web-acl \
  --profile bon-odori \
  --region us-east-1 \
  --scope CLOUDFRONT \
  --name bonsuke-site-prod-web-acl \
  --default-action Allow={} \
  --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=bonsukeSiteProdWebAcl \
  --rules file://infra/waf-cloudfront-managed-rules.json
```

Associate WAF to CloudFront:

```bash
ACCOUNT_ID="$(aws sts get-caller-identity --profile bon-odori --query Account --output text)"
WEB_ACL_ARN="$(aws wafv2 list-web-acls --profile bon-odori --region us-east-1 --scope CLOUDFRONT --query \"WebACLs[?Name=='bonsuke-site-prod-web-acl'].ARN | [0]\" --output text)"

aws wafv2 associate-web-acl \
  --profile bon-odori \
  --region us-east-1 \
  --web-acl-arn "$WEB_ACL_ARN" \
  --resource-arn "arn:aws:cloudfront::$ACCOUNT_ID:distribution/ERA76BJB7WLEN"
```

Create Route53 A/AAAA ALIAS records:

```bash
CLOUDFRONT_DOMAIN="$(aws cloudfront get-distribution --profile bon-odori --id ERA76BJB7WLEN --query 'Distribution.DomainName' --output text)"

aws route53 change-resource-record-sets \
  --profile bon-odori \
  --hosted-zone-id "$HOSTED_ZONE_ID" \
  --change-batch file:///tmp/bonsuke-route53-alias.json
```

The alias target must be:

- `DNSName`: CloudFront domain, for example `dxxxx.cloudfront.net`
- `HostedZoneId`: `Z2FDTNDATAQYW2`
- `EvaluateTargetHealth`: `false`

## Verification

```bash
dig +short NS "$DOMAIN_NAME"
dig +short A "$DOMAIN_NAME"
dig +short AAAA "$DOMAIN_NAME"
curl -I "https://$DOMAIN_NAME/"
```

Expected result:

- DNS resolves to CloudFront.
- TLS certificate subject/SAN includes the domain.
- HTTP response is 200, 301, 302, or the existing static site's normal response.

## Rollback

1. Remove Route53 ALIAS records.
2. Remove CloudFront aliases and restore the default CloudFront certificate.
3. Disassociate WAF WebACL if needed.
4. Keep the ACM certificate for a short observation period, then delete if no
   longer needed.
