# Review Inbox B1-4 Official Bulk Shadow Runbook

作成日: 2026-07-18 JST

署名: おと（Codex）

ステータス: B1-4a配線コード実装、default off、未実行

## フェーズ分離

B1-4は次の二段階に分ける。

1. **B1-4a**: official source bulk shadow CLI、共通安全ゲート、FakeStore検証を実装する。本番RDB/S3へ接続・書き込みしない。
2. **B1-4b**: B1-4aのことレビュー・merge後、内田さんの別最終GOを得て、official source全件を初めて正本へ書きCAS publishする。

この文書を含むB1-4a PRではB1-4bを実行しない。workflow/cronへの自動配線も行わない。

## 入力とbulk selection

`run_review_inbox_official_bulk_shadow.py` は、PR #44でmainへ入った
`OfficialSourceAdapter`を使い、`data/official_source_review_candidates.json`の同一bytesを
凍結snapshotへ変換する。2026-07-18時点の実データは52件（historical 47 / future 5）である。

snapshotには次を固定する。

- `source_id=official_source`
- `selection.mode=all`
- 全source keyの集合
- input path / SHA-256 / byte数
- adapter snapshot path / SHA-256
- `target_year`とtime scope別件数

1runの全stable IDをcurrent observationとしてparity比較する。入力から消えた既存pending行は削除せず
`stale_candidates`へ分類し、decision済み行はlifecycleを保持する。未分類があれば停止する。

## CLI安全ゲート

ArtifactStoreを生成する前に、次をすべて満たす必要がある。

1. `--execute`
2. `--confirm 'RUN OFFICIAL SOURCE BULK SHADOW'` 完全一致
3. 次の4環境変数を省略せず明示
4. JST 17:20以上18:00未満のcron帯ではない
5. `observation-id`、固定`expect-rstart-checksum`、固定`public-today`が有効
6. input、snapshot、reportのパスが別で、既存証跡を上書きしない
7. official adapterが1件以上を返し、source keyに重複がなく、`selection=all`

```text
REVIEW_INBOX_DUAL_WRITE_MODE=bulk
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true
REVIEW_INBOX_READER_MODE=legacy
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true
```

環境変数未設定時はdual-write off / CAS offである。reader切替、legacy writer停止、canary selectionは
このCLIから実行できない。`--force`引数も存在せず、production ArtifactStoreのpublishはforce false固定である。

## B1-4b実行テンプレート（最終GO後だけ）

以下はB1-4a PRでは実行しない。merge後にことが提示するRstart、証跡ディレクトリ、実行時刻を確認し、
内田さんのB1-4b最終GOを得てから使う。

```bash
REVIEW_INBOX_DUAL_WRITE_MODE=bulk \
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true \
REVIEW_INBOX_READER_MODE=legacy \
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true \
python3 run_review_inbox_official_bulk_shadow.py \
  --execute \
  --confirm 'RUN OFFICIAL SOURCE BULK SHADOW' \
  --observation-id '<approved-scheduled-run-id>' \
  --expect-rstart-checksum '<ことが直前確認したRstart SHA-256>' \
  --public-today '<YYYY-MM-DD>' \
  --target-year 2026 \
  --snapshot-out '<new-evidence-dir>/official-adapter-snapshot.json' \
  --report-out '<new-evidence-dir>/official-run-report.json'
```

bucket/prefixは承認済み値を引数または既存環境から渡す。本番実行はcron帯へ入る見込みがある場合も開始しない。

## 停止条件とB1-4閉鎖条件

B1-2/B1-3の停止条件を継承する。Rstart不一致、fetch SHA不一致、schema/integrity/FK異常、
inbox以外へのwrite、parity差、unmapped、lifecycle変化、domain/public差、CAS conflict、Rend別fetch差の
いずれかでpublishせず停止する。force retryは禁止する。

B1-4b初回成功は、B1-4閉鎖に必要な「2連続実スケジュールrun parity」の1回目として扱う。
2回目も実スケジュールrunでparity 0差分を確認し、decision往復・rollback・route境界など
`review-inbox-b1-dual-write-plan.md` §8の全条件が揃うまでlegacy writer/reader/apply経路を維持する。
