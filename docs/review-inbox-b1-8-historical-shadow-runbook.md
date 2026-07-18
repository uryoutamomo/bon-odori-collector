# B1-8 historical reference shadow runbook

B1-8aは`historical_promotion_candidates`をreview-onlyの`historical_reference` sourceへ配線する。
コード、凍結入力、テスト、runbookのみを追加し、このPRでは本番S3を変更しない。B1-8bはmain
merge、こと独立レビュー、内田さんの別GO、直前Rstart実測を済ませてから行う。

## 凍結する実入力

| input | input SHA-256 | source DB SHA-256 | candidates | current identity |
| --- | --- | --- | ---: | ---: |
| `data/review_inbox_inputs/historical_reference_current_identity.json` | `160698aa048f557acd2dc039f738c081cc8042f175fe36700323a7e5eac7b0aa` | `e8e6b1f69de0551bdc84ba52e161883889eccb0da3b454da6a8abf94a366a5ce` | 16 | 16 included / 0 excluded |

入力はRend6 snapshot `20260718T051023Z` の
`historical_promotion_candidates` tableからread-onlyで生成した。repoに以前からあるlegacy JSONは15件で、
Rend6 tableにのみ存在する`manual_predicted_date_review` 1件を含まないため、B1-8の正本入力には
使わない。

current identityの条件は、`target_series_id`と`target_occurrence_id`が現在のdomain tableで解決し、
そのoccurrenceがtarget seriesに所属すること。今回の16件はすべて条件を満たす。将来、解決不能または
series不一致になった候補はbuilderが除外し、adapterも不正なidentity markerをfail-closedで拒否する。
source keyは`target_occurrence_id`で、16件すべて一意である。

## promotion neutralization

| legacy action | review inbox action | count |
| --- | --- | ---: |
| `auto_promote_historical_reference` | `review_historical_reference` | 13 |
| `manual_review_multi_year_history` | `research_multi_year_history` | 2 |
| `manual_predicted_date_review` | `review_prediction_queue` | 1 |

全行を`kind=historical_reference`、`time_scope=reference`としてpending reviewへ写す。adapterは未知actionを
拒否する。entrypointでも`promote_`、`auto_promote_`、`apply_` prefixと
`confirm_current_year_date`、`update_venue`、`fill_source_url`を二重に拒否する。promotion、domain apply、
current-year confirmは行わない。

## fail-closed境界

- CLIは既定off。`--execute`と完全一致confirmがなければsnapshot生成前に停止する。
- 4環境変数は`bulk / true / legacy / true`の完全一致を要求する。
- `17:20-18:00 JST`、不正なRstart、既存証跡path、空入力、重複source keyで停止する。
- 凍結入力内のsource DB SHAとoperator固定Rstartが異なればS3 store生成前に停止する。
- S3 statusで再実測したRstartがoperator固定値と異なればfetch/publish前に停止する。
- domain table不触、public digest不変、decision自動設定0、S3別fetch実体SHA、CAS
  `expect-rstart`・force無しは共通writerで検査する。
- workflow配線、reader切替、legacy writer停止、domain applyはB1-8の範囲外。

## B1-8b実行条件

1. B1-8aをmainへmergeし、ことがコード・入力16件・action neutralizationを独立検証する。
2. 内田さんからB1-8b本番実行の別GOを受ける。
3. cron帯外でS3 statusを再取得し、その場でRstart checksumとsnapshot IDを固定する。
4. Rend6を想定値にはできるが、実測値と一致しない場合は実行せず停止する。
5. 固有observation IDと未使用のsnapshot/report pathを用意する。
6. 次の4ゲートを明示し、完全一致confirmを渡して1回だけ実行する。

```text
REVIEW_INBOX_DUAL_WRITE_MODE=bulk
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true
REVIEW_INBOX_READER_MODE=legacy
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true
RUN HISTORICAL REFERENCE SHADOW
```

実行後は、16 pending行、action分布13/2/1、parity、stale候補、domain/public不変、decision 0、
published/Rend、S3から別fetchした実体SHAを証跡化し、ことが独立検証する。rollbackが必要な場合は、
直前の既知良好DBを対象に現在Rendを`expect-rstart`としてCAS publishする。force publishは使わない。
