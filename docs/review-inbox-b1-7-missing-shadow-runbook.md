# B1-7 missing source / venue shadow runbook

B1-7aは`missing_source_url`と`missing_venue`を別sourceとして配線する。コードとテストのみで、
このPRでは本番S3を変更しない。各sourceの本番runはmain merge、こと独立レビュー、source別GO、
直前Rstart実測を済ませてから1本ずつ行う。

## 凍結する実入力

| source | input | SHA-256 | items | scope / kind | action |
| --- | --- | --- | ---: | --- | --- |
| `missing_source_url` | `data/missing_source_url_review.json` | `d4f11ada1d5d977b2c2bdce01b187fc2d0ed79426df46f4de1165ff4c27ef0e0` | 0 | empty current snapshot | empty |
| `missing_venue` | `data/missing_occurrence_venue_review.json` | `7c6c483c1ee840702c0e32ac16d73e029b5340df9804799537af2971d7d9fca4` | 3 | future 3 / venue_review 3 | `research_event_name_and_venue` 1、`research_missing_venue` 1、`research_new_venue_source` 1 |

`missing_source_url`の0件は欠落やfixtureではなく、現行legacy builder出力の実状態である。adapterは
空のfull snapshotを保持し、初回runはparity 0件のno-opとしてS3をpublishしない。将来入力に行が
再発した場合も、有限actionをresearchまたはchange-request stageへ写すだけで`fill_source_url`を
直接実行しない。

`missing_venue`のsource keyは3つの`occurrence_id`で、source内重複はない。別sourceのstable IDは
`kind + source_id + source_key`で分離される。3件はすべて2026年のfuture行で、legacy actionは
調査用actionへ写す。候補payloadと根拠URLは保持するが、`update_venue`を直接実行しない。

## fail-closed境界

- CLIは既定off。`--execute`とsource別の完全一致confirmがなければsnapshot生成前に停止する。
- 4環境変数は`bulk / true / legacy / true`の完全一致を要求する。
- `17:20-18:00 JST`、不正なRstart、既存証跡path、重複source key、未知actionで停止する。
- `confirm_current_year_date`、`fill_source_url`、`update_venue`をadapterが出した場合は停止する。
- domain table不触、public digest不変、decision自動設定0、S3別fetch実体SHA、CAS
  `expect-rstart`・force無しは共通writerで検査する。
- workflow配線、reader切替、legacy writer停止、domain applyはB1-7の範囲外。

## source別実行順

1. cron帯外を確認し、S3 statusからRstartとsnapshot IDを実測する。
2. `source-url`を固定入力、固有observation、固有証跡pathで実行する。現入力0件なら
   `published=false / no_op=true / Rend=Rstart`を要求する。
3. ことがS3実体、parity、domain/public、decision 0を独立検証する。
4. 再度Rstartを実測し、`venue` 3件を別runとして実行する。
5. ことが3件のpending lifecycle、action分布、S3実体、domain/publicを独立検証する。

確認句は次の完全一致とする。

```text
RUN MISSING SOURCE URL SHADOW
RUN MISSING VENUE SHADOW
```

rollbackが必要な場合は、直前の既知良好DBを対象に現在Rendを`expect-rstart`としてCAS publishする。
force publishは使わない。
