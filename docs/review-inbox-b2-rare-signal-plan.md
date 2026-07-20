# B2 rare signal / X・RSS inbox plan

Updated: 2026-07-19 JST

署名: おと（Codex）

Status: B2-3b canary shadow upsert verified; B2-3c decision CAS writer verified; B2-5 scheduled dual-write wiring default off

## Scope

B2は `x_news_digest_for_oto → rare_signal → non-X backcheck → registration candidate`
のうち、人間判断が必要なrare signalだけをMaster RDBのreview inboxへ集約する。

この段階では次を変更しない。

- X/RSS収集範囲、X API予算、`collect.yml`の実行順
- DynamoDBの裏取り・イベント候補queue契約
- Master RDB、公開JSON、Notion、domain tableへのapply
- legacy `rare_signal_backcheck` console source / JSON writer
- reader mode、workflow、production writer

## Current inventory

2026-07-18生成の `data/x_news_digest_for_oto.json` は4,908候補を持つ。一方、
`x_news_digest_oto_reviews.json`、`rare_signal_candidates.json`、backcheck queue、
registration candidatesは現在のmain入力には存在せず、consoleのlegacy rare signal pendingも0件である。

raw digestは機械下ごしらえであり、人間queueではない。4,908件をinboxへ直接投入しない。
おとの解釈でpromoteされた候補だけをbackcheck queueへ進め、そのqueueをB2 adapterの入力にする。

## Inbox contract

| field | contract |
|---|---|
| `kind` | `rare_signal` |
| `source_id` | `rare_signal` |
| legacy mapping | `rare_signal_backcheck → rare_signal` |
| `time_scope` | event / venue は `future`、song / existing evidence は `reference` |
| input | Oto-interpreted `rare_signal_backcheck_queue.json` only |
| excluded input | raw `x_news_digest_for_oto.json` and raw search results |
| apply boundary | decision stagingまで。DB / public / DynamoDBへ直接書かない |

### Stable identity

現行のmachine `candidate_id` はURL・information typeに加えて要約文字列の影響を受けるため、
adapterの唯一のstable keyにはしない。

adapterは次を優先してsource keyを作る。

1. X/Twitter URLのimmutable status ID。
2. その他URLはscheme/host/path/queryをcanonicalizeし、fragmentを除外する。
3. `information_type` と `promotion_target` をidentityへ含める。
4. immutable URLがない手動候補だけ、既存の永続candidate IDへfallbackする。

表示名、候補名、おとの要約、URLのX/Twitter表記差が変わっても同じstable IDを維持する。
同じimmutable discoveryが二重に入力された場合は黙ってdedupeせずfail closedする。

## Action boundary

B2-1 adapterが出せるrecommended actionは次に限定する。

| upstream action | inbox action |
|---|---|
| `find_non_x_confirmation` | `research_non_x_confirmation` |
| `review_official_social_post` | `review_registered_official_social` |
| `review_source_account_then_find_confirmation` | `review_source_account_and_confirmation` |

adapterはstatus、decision、reviewer、route、timestampsを生成しない。legacy payload内のdecision-like
fieldをinbox lifecycleへ昇格しない。

B2-2では次のdecision routeを実装する。

- `needs_research` → `research_followup`
- `hold` / `reject` → `no_apply`
- `accept` → 非X URLを必須にしたregistration candidate staging
- X URLしかないaccept → fail closed（apply packet 0）

acceptは共通の `domain_stage` route内で
`domain_stage_type=rare_signal_registration_candidate` の有限packetへ変換する。
確認URLはレビューのメモまたはsource payloadの `confirmed_source_urls` から取り、
X/Twitter/t.coを除いたURLが1件もなければstage全体を失敗させる。
このpacketはMaster RDB、domain table、DynamoDB、公開JSONを更新しない。

event/song/venue/existing evidenceのどのtargetでも、staging後のdomain applyは別レビューとGOを必要とする。

## Delivery stages

1. **B2-1 pure adapter**: adapter、佐竹/鉄砲洲fixture、input hash、stable ID、payload hash、parity test。
2. **B2-2 decision route**: finite decision packetと非X URL fail-closed。production変更なし。
3. **B2-3 canary**: B2-3aでdefault-off配線、B2-3bの別GO後に1件だけshadow upsertし、
   正本decision CAS writer整備後のB2-3cでdecision round-tripと再観測保持を検証。
4. **B2-4 full shadow**: Oto-promoted対象だけを投入し、legacy残高をunmapped 0へ分類。
5. **B2-5 scheduled dual-write**: 別workflow PR・別GOでlegacy JSON/DynamoDBを維持したまま2実run観測。
6. **B2 cutover**: reader cutover後さらに1実runを監視し、10閉鎖条件後にlegacy UI writer停止を判断。

DynamoDBを収集bufferとして残すかRDBへ寄せるかはB2 cutoverとは別PRで決定し、B2では削除しない。

## B2-5 default-off workflow wiring（2026-07-20）

`collect.yml` は、同じrunで `rare_signal_backcheck_queue.json` を生成できた場合に限り、
`run_review_inbox_rare_signal_scheduled.py` を呼べる配線を持つ。実行にはrepository variable
`REVIEW_INBOX_RARE_SIGNAL_DUAL_WRITE_ENABLED=true` が必要で、未設定時はstep自体がskipされる。

有効時もlegacy JSON writer、DynamoDB、reader modeは変更しない。runnerはbulk snapshotを固定し、
schema v2、source parity、unmapped 0、lifecycle保持、integrity/FK、domain table count、public projectionを
検査してからCAS publishする。成功後はRendを別fetchし、pendingだけの `data/review_inbox.json` を再投影する。
証跡snapshot/reportはworkflow artifactとして30日保持する。

通常collect成果のcommit/pushをdual-writeより先に完了させる。これによりCAS conflictやS3一時障害で
dual-writeがfail closedしても、news・voices・公開JSONなど同日の収集成果を道連れにしない。
dual-write成功時だけRend由来の `review_inbox.json` を2つ目の限定commitで保存し、失敗はworkflowを赤く保つ。

本PRは配線コードとテストまでで、repository variable設定、workflow実行、merge、本番DB更新、
reader切替、legacy writer停止、domain/public applyを含まない。最初の2 scheduled observationsは、
本PRのmerge後に別GOでvariableを有効化して取得する。

## B2-1 acceptance

- adapterはI/Oやexternal writeを行わない。
- input SHA-256、input size、source keysをsnapshotへ記録する。
- 佐竹ゲバゲバ盆踊り（非X裏取り）と鉄砲洲納涼盆踊り（registered official social）をfixture化する。
- 可変summary/candidate ID/X vs Twitter URL表記が変わってもstable IDが一致する。
- unsupported target/action、duplicate stable IDはfail closedする。
- adapted snapshotと同じinbox projectionのparityがmissing/extra/mismatch `0/0/0`になる。
- workflow、reader、writer、DynamoDB、DB、publicへの変更がdiffに含まれない。
