# B3 YouTube aggregate scheduled dual-write runbook

## 境界

`collect.yml` の通常収集commitが完了した後、repository variable `REVIEW_INBOX_YOUTUBE_AGGREGATE_DUAL_WRITE_ENABLED=true` の場合だけ動く。legacy `youtube_active_video_review.{json,md}` と `youtube_year_backfill_review_queue.{json,md}` を再生成して先にcommitし、checked-inの `youtube_user_confirmation_queue.json` と合わせたcomplete aggregateを統合受信箱へCAS dual-writeする。

既定はOFF。legacy readerとlegacy JSONを維持し、Master RDBでは `review_inbox_items` 以外を書き換えない。domain table件数と公開projection digestはRstart、更新中、Rend再fetchの3点で不変を確認する。

## 実行ゲート

- repository variableがtrue
- `MASTER_DB_S3_BUCKET` が設定済み
- runnerの `--execute`
- aggregate schema version 1、active/year/userの3入力lineage、監査済みprecedenceが完全一致
- 3入力とsnapshot/reportのpathがすべて別
- confirm文字列 `RUN SCHEDULED YOUTUBE AGGREGATE DUAL WRITE` が完全一致
- dual-write bulk / CAS publish / reader legacy / legacy writer enabled の4環境ゲート
- 17:20〜18:00 JST外
- fresh legacy builder stepが成功済み

## 証跡

各runでaggregate snapshotとCAS/parity reportをGitHub artifactへ30日保存する。snapshotには3入力のpath・SHA-256・size・item count、重複時の選択queueとpayload hashを残す。reportではlegacy pendingとinbox currentのstable ID、内容、unmapped、domain/public不変、Rstart/Rend checksumを確認する。projection commitはdual-write成功時だけ行う。

## 観測とrollback

連続2回の実スケジュールrunでstable key集合と内容差分0を確認するまでlegacy JSON/readerを止めない。異常時はaggregate variableをfalseへ戻し、必要なら旧active-only runnerとvariableへ一時rollbackできる。既存legacy収集とreaderはその間も残す。

おと（Codex）
