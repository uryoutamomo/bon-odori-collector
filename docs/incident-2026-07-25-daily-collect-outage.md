# 2026-07-25 日次収集(bon-odori-collect)停止の記録

署名: こと（Claude Code）

## 何が起きたか

`bon-odori-collect` が **2026-07-21 から 5日連続で失敗**していた（最後の成功は 7/20）。
シーズン最盛期にもかかわらず **7/23・7/24・7/25 はデータコミットが1本もなく**、
ニュース・X声・公式監視の収集自体が動いていなかった
（7/21・7/22 は収集本体は成功し、後段の dual-write だけ失敗）。

発見の経緯は「YouTube年次バックフィルの最新実行が6月のまま」という表示の調査。
そこから日次パイプライン全体の健康状態を確認して判明した。

## 原因は4つ、直列に隠れていた

前の原因を直すと次が出てくる形で、都合4件が積み重なっていた。

### 1. cron窓ガードの自爆（7/21〜）

`review_inbox_adapters/shadow_execution_gate.py` は 17:20-18:00 JST の実行を禁止する。
`collect.yml` の cron は 15:13 JST だが、GitHub のスケジュール遅延で
**7/21〜25 は毎日 17:22〜17:43 JST に起動**し、この窓に着地していた。
結果、cron を守るためのガードが cron 自身を毎日弾いていた。

この窓の目的は「日次cronが master RDB を触っている間に別プロセスが割り込まない」こと。
cron 自身は Actions の concurrency group (`bon-odori-master-rdb`) で直列化されており、
窓の"主"なので避ける必要がない。`collect.yml` の dual-write 3ステップだけが
`REVIEW_INBOX_CRON_SERIALIZED_RUN` を明示して除外する。
手動・canary 実行は環境変数を持たないのでガードが残る。

### 2. リファクタリングの参照漏れ（7/23〜）

`92ce4c7` で `master_db.py` が `master_rdb/` 配下へ移設された際、
`collect.yml:93` の `python -c` だけ古い参照のまま残り
`ModuleNotFoundError: No module named 'master_db'` で落ちていた。
本体コードは全て `from master_rdb.master_db import` に更新済みだった。

### 3. review inbox スキーマの退行

master RDB の `review_inbox_items` が 17列(v1)で、v2 の8列
(`time_scope` `decision` `decided_by` `decided_at` `closed_at` `decision_route`
`source_payload_hash` `last_seen_at`) が欠けていた。
dual-write 側は "does not migrate schema" 設計なので
`review inbox schema v2 is required` で失敗する。

7/20 には動いていたので、その後に **v1系統のDBが本番を上書き**した形。
7/24 に手作業由来の publish が6回集中しており、その辺りが濃厚。

**なぜ気づけなかったか**: `master_db_s3_artifact.py publish` のガードは
「新しい成果を上書きしない」ためのチェックサム照合(CAS)だけで、
**スキーマ退行を見ていない**。日次監査にも検査項目がなかった。

コード側の DDL (`review_inbox.py` / `master_rdb/master_db.py`) は両方とも25列だが、
`CREATE TABLE IF NOT EXISTS` は既存テーブルに列を足さないため、
一度 v1 で作られたテーブルは放置されると永久に v1 のまま。

### 4. publication_gap の action 許可リスト漏れ

`build_publication_gap_review.py` が出す
`review_and_apply_event_occurrence_to_master_rdb`（実データ208行中49行）を
`PublicationGapAdapter` が知らず、`unsupported publication gap action` で
low-priority dual-write が失敗していた。

## 対応

| # | 対応 | コミット |
|---|---|---|
| 1 | scheduled 実行を cron窓ガードの対象外にする | `6c771b6` |
| 2 | `collect.yml` の import を `master_rdb.master_db` に修正 | `6c771b6` |
| 3 | Actions から移行を回す workflow を追加 → dry-run → apply | `4568b41` |
| 3 | 監査に inbox スキーマ退行検知を追加(high severity) | `b78223f` |
| 4 | 許可リストに action を追加 | `b78223f` |

`migrate-review-inbox-v2` workflow は既定 dry-run、apply は
`confirm='APPLY REVIEW INBOX V2'` との二重ゲート。
移行の監査9項目（integrity / foreign_key / legacy_rows_unchanged /
domain_table_counts_unchanged / no_decision_auto_promotion 等）は全て PASS。

## 結果

2026-07-26 00:34 の通し実行で **全ステップ success**。
`Dual-write complete YouTube aggregate` / `low-priority` とも通り、
inbox projection のコミットまで到達した。

## 残っている注意点

- **cron窓ガードの修正は実地検証がまだ**。復旧の手動実行はいずれも窓の外
  (23:52 / 00:26 JST) だったため、窓内で通ることはユニットテストでしか
  確認できていない。次の定時実行（遅延して17時台に入る想定）で確認すること。
- GitHub のスケジュール遅延は今後も起きる。cron 時刻を早める案もあるが、
  遅延幅は日によって変わるため、ガード側を正しくした方が筋が良い。
- **RDB を手元で触って publish する運用**が今回の3番の遠因。

## publish 時点で止める（2026-07-26 追加）

3番は監査で翌日に気づけるようになっただけで、publish 自体は退行を通していた。
そこを塞いだ。

`master_db_s3_artifact.py publish` が manifest に
`review_inbox_schema_version` を載せ、publish 前にリモートの値と比較する。
ローカルがリモートより古ければ `review inbox schema downgrade blocked` で
中断し、S3 には何もアップロードしない。意図的な退行は `--force` で通せるが、
その場合も警告を出す。`status` は両側の版を並べて表示する。

判定は監査(`master_rdb/audit.py`)と同じ `inbox_schema_version` を使い、
テーブルが無い場合も v1 扱いにする。v2 前提の dual-write から見れば
使えないことに違いはなく、退行ガードとしても安全側に倒れる。

移行期間の穴が一つある。このガードより前に publish された manifest には
キーが無く比較できない。そこで止めると次の定時 publish が落ちてしまうので、
キーが無い場合は notice を出して通す。一度 publish されれば以後は必ず載る。

実地で効くことも確認できた。この作業時点のローカル
`data/bon_odori_master.sqlite`（git追跡外・7/25 03:16 の fetch）は
**17列の v1 のまま**で、移行前の状態だった。手元から publish していれば
本番を v1 に戻して同じ停止を再発させていた。
