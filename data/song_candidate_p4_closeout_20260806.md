# 曲候補P4 本番反映 closeout

日時: 2026-08-06 02:39 JST
署名: おと（Codex）

## 結果

統合レビュー受信箱で内田さんが判断した5件を、本番Master RDBの有限action反映結果と照合した。

| 候補 | 受信箱 | 判断 | Master RDB |
|---|---|---|---|
| 防災神神音頭 | `inbox_d4e619d16d18f4be` | accepted | `active` |
| BON踊り | `inbox_675177050e6cb942` | rejected | `無効` |
| ドン踊り | `inbox_3ae38feccaeb0592` | rejected | `無効` |
| 盆ジョビ | `inbox_17fe85f1bcfa7dd2` | rejected | `無効` |
| 風流踊り | `inbox_ba760db4c9ebe011` | rejected | `無効` |

全5件で、受信箱の `status` / `decision` / `decided_by` / `closed_at` と、曲マスタの `status` が対応している。

## 本番artifact

- snapshot: `20260805T172254Z`
- published_at: `2026-08-05T17:22:54.189667+00:00`
- checksum: `cf1861b7d0dd5ef4a79e738715936871b5554c74fc4ebf082cc7632e0e4edcd3`
- `songs`: 399
- `song_aliases`: 142
- `review_inbox_items`: 542
- review inbox schema: v2

ローカルDBのSHA-256と更新manifestの `database_checksum` は一致した。
GitHub Actions `verify-master-rdb-s3` run
[`31030943237`](https://github.com/uryoutamomo/bon-odori-collector/actions/runs/31030943237)
で本番S3 latestを再取得し、Master RDB監査 `issues=0`、未追跡DBガード合格を確認した。

## 公開差分

曲候補P4による公開曲projectionの変更はない。
同時に再生成された公開イベント差分は、日付経過により「鉄砲洲納涼盆踊り」が
`upcoming_confirmed` から `ended_2026` へ移った1件だけである。

`guard_public_events_sync --report-only` は `status=pass`、
`safe_to_wholesale_sync=true`。`master_rdb_newer_than_publication_gap_review` の
手順警告は残るが、差分は上記1イベントの2フィールド群だけで、ブロック対象はない。

## ローカルbackup

適用前Rstart backupは `data/song_candidate_apply_backups/` に保持する。
SQLite本体と同様にGitへは入れず、今回 `.gitignore` の対象へ追加した。
