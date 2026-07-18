# Review Inbox B1-6 Predicted Sources Shadow Runbook

作成日: 2026-07-18 JST

署名: おと（Codex）

ステータス: B1-6a配線コード実装、default off、未実行

## Source分離

B1-6は予測に関する二つの既存human-review artifactを扱う。閉鎖判定、stable ID、snapshot、CAS runを
混ぜないため、同じ`kind=predicted_date`でも別source_idとする。

| source | input | 2026-07-18実件数 | source_id |
|---|---|---:|---|
| research | `data/predicted_occurrence_research_queue.json` の`items` | 8 | `predicted_occurrence_research` |
| date review | `data/predicted_occurrence_date_review.json` の`review` | 12 | `predicted_occurrence_date_review` |

research 8件はdate review 12件にも同じ`predicted_date_id`で現れるが、source_idが異なるためinbox IDも
別になる。同じ予測に対する「根拠再調査」と「予測日レビュー」を独立した仕事として保持する。

## 実データ分布とRDB 14件との関係

researchは8件すべてfuture / predicted dateで、priorityはP0 4、P1 3、P2 1。
date reviewは12件すべてfuture / predicted dateで、legacy actionはkeep queue 8、already matches curated 1、
already superseded 3である。

本番Master RDBの`predicted_occurrence_dates`は現在14行だが、review inboxが読む正本入力は上記の凍結JSONである。
JSONはRDB行そのものの複製ではなく、各builderが生成したhuman-review projectionであり、生成時刻と選択条件も異なる。
したがって8/12/14を同一集合として数合わせしない。各run内ではinput bytesのSHAとadapter全件のparityを閉じ、
RDB 14行には書かない。source閉鎖前に次の実スケジュールbuilderで入力再生成と残高対応を確認する。

## 予測と当年確定の安全境界

adapterは二sourceとも`kind=predicted_date`、`time_scope=future`を設定するが、開催確定は行わない。

- researchのactionはsource recheck / prediction queue維持の3値だけを許す。
- date reviewの`current_status`、`review_action`、`confidence`、既存application statusはpayloadにのみ保持する。
- date reviewのrecommended actionはpredictionのqueue/match/supersession検証に限定する。
- adapterはstatus、decision、reviewer、decision route等のlifecycle fieldを生成しない。
- acceptされても`confirm_current_year_date` change requestを自動生成しない。当年確定には別途公式根拠が必要。

## Entry pointと壊さない5点

`run_review_inbox_predicted_shadow.py --source research|date-review`を使い、sourceごとに別実行する。
共通ゲート、Rstart、証跡パス、observation ID、CAS publishも別にする。

```text
REVIEW_INBOX_DUAL_WRITE_MODE=bulk
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true
REVIEW_INBOX_READER_MODE=legacy
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true
```

confirmはsourceごとに完全一致させる。

- research: `RUN PREDICTED OCCURRENCE RESEARCH SHADOW`
- date review: `RUN PREDICTED OCCURRENCE DATE REVIEW SHADOW`

各runでdomain不触、public digest不変、decision自動昇格0、S3別fetch実体SHA、Rstart/CAS/forceなしを
独立検証する。一方が合格しても他方を同一transactionや同一CASへまとめない。異常時は次runへ進まない。

## B1-6b実行順

ことレビュー合格・merge後、cron帯外で次の順に行う。

1. status実測Rstartを固定し、research 8件を実行・独立検証する。
2. research Rendを次の直前Rstartとして再測定し、date review 12件を実行・独立検証する。
3. 二source合計20行がpending / decision系NULLで、既存registered 79・official 52を保持することを確認する。

workflowへの自動配線はB1-6に含めない。
