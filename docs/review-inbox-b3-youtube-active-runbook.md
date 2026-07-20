# B3 YouTube active video scheduled dual-write runbook

## 境界

`collect.yml` の通常収集commitが完了した後、repository variable `REVIEW_INBOX_YOUTUBE_ACTIVE_DUAL_WRITE_ENABLED=true` の場合だけ動く。最初にlegacy `youtube_active_video_review.{json,md}` を全active channel対象で再生成してcommitし、その確定JSONを統合受信箱へCAS dual-writeする。

既定はOFF。legacy readerとlegacy JSONを維持し、Master RDBでは `review_inbox_items` 以外を書き換えない。domain table件数と公開projection digestはRstart、更新中、Rend再fetchの3点で不変を確認する。

## 実行ゲート

- repository variableがtrue
- `MASTER_DB_S3_BUCKET` が設定済み
- runnerの `--execute`
- confirm文字列 `RUN SCHEDULED YOUTUBE ACTIVE DUAL WRITE` が完全一致
- dual-write bulk / CAS publish / reader legacy / legacy writer enabled の4環境ゲート
- 17:20〜18:00 JST外
- fresh legacy builder stepが成功済み

## 証跡

各runでadapter snapshotとCAS/parity reportをGitHub artifactへ30日保存する。reportではlegacy pendingとinbox currentのstable ID、内容、unmapped、domain/public不変、Rstart/Rend checksumを確認する。projection commitはdual-write成功時だけ行う。

## 観測とrollback

連続2回の実スケジュールrunでstable key集合と内容差分0を確認するまでlegacy JSON/readerを止めない。異常時はrepository variableをfalseへ戻すだけで次runからbuilder・dual-writeとも停止し、既存legacy収集とreaderはそのまま残る。

おと（Codex）
