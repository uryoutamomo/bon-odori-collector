# Song candidate finite-action operations

作成: 2026-08-06 JST
署名: おと（Codex）

## Purpose

統合レビュー受信箱の `kind=song` を、人が選んだ有限actionのまま
Master RDBの `songs` / `song_aliases` へ反映する。

選択肢は次の4つだけとする。

- `register_song`: 新規登録、または既存の候補曲をactiveへ昇格
- `add_song_alias`: 指定した既存 `song_id` の別名として登録
- `reject_song`: 曲ではない文字列として無効化
- `hold`: 判断を保留し、曲マスタは変更しない

自由記述からactionを推測しない。`add_song_alias` だけは対象 `song_id` を必須とし、
ほかのactionで `song_id` が指定されていたら停止する。

## Safety boundary

この経路は2段階のCAS publishである。

1. review inbox lifecycleだけを反映する
2. 1のRend checksumを次のRstartに固定し、曲マスタ有限actionを反映する

各段階は、backup・integrity/FK監査・公開projection不変・Rend再fetchを通す。
1の後に2が失敗しても、同じ凍結証跡と1のRendから2だけを安全に再実行できる。

workflowにはまだ配線しない。本番実行は、内田さんが対象batchと工程を明示承認した場合だけ
このrunbookのdefault-off CLIで行う。

## 1. Review and stage

review consoleをinbox readerで開き、曲候補ごとに4actionのどれかを選ぶ。
別名統合の場合は対象 `song_id` も入力する。

consoleのexport/stage後、少なくとも次の2ファイルが生成される。

- `data/review_console/staged/review_inbox_song_candidate_decision_updates.json`
- `data/review_console/staged/review_inbox_song_candidate_actions.json`

後者はaccepted/rejected/holdのrouteをまたいで、曲候補だけを1つの凍結packetにまとめる。

## 2. Build the trusted P4 payload

```bash
python3 -m scripts.build_song_candidate_finite_payload \
  --staged-actions data/review_console/staged/review_inbox_song_candidate_actions.json \
  --out-json data/review_console/staged/song_candidate_reviewed_finite_actions.json
```

このコマンドは純粋なファイル変換で、RDBやS3へ接続しない。

## 3. Write the review lifecycle

実行直前に本番RDB statusを取り直し、Rstart checksumを固定する。
cron帯外で、4環境ゲートを明示して実行する。

```bash
REVIEW_INBOX_DECISION_WRITE_MODE=bulk \
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true \
REVIEW_INBOX_READER_MODE=legacy \
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true \
python3 -m scripts.run_song_candidate_decision_write \
  --staged-decisions data/review_console/staged/review_inbox_song_candidate_decision_updates.json \
  --staged-actions data/review_console/staged/review_inbox_song_candidate_actions.json \
  --frozen-evidence-dir data/song_candidate_decision_evidence/<batch-id> \
  --report-out data/song_candidate_decision_evidence/<batch-id>-decision-report.json \
  --expect-rstart-checksum <64hex-Rstart> \
  --public-target-year 2026 \
  --public-today <YYYY-MM-DD> \
  --bucket "$MASTER_DB_S3_BUCKET" \
  --prefix "${MASTER_DB_S3_PREFIX:-master-rdb}" \
  --execute \
  --confirm 'WRITE SONG CANDIDATE DECISIONS'
```

reportの `rend.checksum` を次の工程のRstartに使う。途中で別writerがRDBを変更した場合は
古いchecksumを使わず、差分を再確認して最初からやり直す。

## 4. Dry-run and apply the finite actions

まず `--apply` なしでdry-runする。

```bash
python3 apply_song_candidate_finite_actions.py \
  --reviewed-payload data/review_console/staged/song_candidate_reviewed_finite_actions.json \
  --bucket "$MASTER_DB_S3_BUCKET" \
  --prefix "${MASTER_DB_S3_PREFIX:-master-rdb}" \
  --expect-rstart-checksum <phase-1-Rend> \
  --target-year 2026 \
  --today <YYYY-MM-DD> \
  --out-json data/song_candidate_decision_evidence/<batch-id>-dry-run.json
```

action件数、対象名、`public_projection_unchanged: true`、監査結果を確認してから本適用する。

```bash
python3 apply_song_candidate_finite_actions.py \
  --reviewed-payload data/review_console/staged/song_candidate_reviewed_finite_actions.json \
  --bucket "$MASTER_DB_S3_BUCKET" \
  --prefix "${MASTER_DB_S3_PREFIX:-master-rdb}" \
  --expect-rstart-checksum <phase-1-Rend> \
  --target-year 2026 \
  --today <YYYY-MM-DD> \
  --apply \
  --confirm 'APPLY SONG CANDIDATE FINITE ACTIONS' \
  --out-json data/song_candidate_decision_evidence/<batch-id>-apply.json
```

完了条件は `published: true`、Rend再fetchの
`action_results_match_plan: true`、公開projection不変である。

## Legacy decisions

旧 `daily_song_candidate:<term>` item_idの判断は、統合受信箱の `inbox_id` と一致しない。
文字列一致だけで自動移行してはならない。旧判断を使う場合は、現在のcandidate、根拠URL、
source_key、現行SongCatalog状態を再確認し、現行UIから新しい有限actionとして保存する。
