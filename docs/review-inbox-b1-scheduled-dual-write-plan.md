# B1 scheduled dual-write closure plan

Updated: 2026-07-19 JST

署名: おと（Codex）

Status: plan only; workflow not wired

## Decision

B1の7 sourceはreader full切替と初回production shadowに合格したが、旧writer閉鎖条件は未完である。
現時点ではlegacy writerを一つも停止しない。

対象sourceと最終固定Rstartのparity件数は次のとおり。

| source | items | unmapped | parity |
|---|---:|---:|---|
| official source | 52 | 0 | true |
| registered event investigation | 79 | 0 | true |
| predicted occurrence research | 8 | 0 | true |
| predicted occurrence date review | 12 | 0 | true |
| missing source URL | 0 | 0 | true |
| missing venue | 3 | 0 | true |
| historical reference | 16 | 0 | true |

上記は一回の固定入力でのcontent parityを示すが、2回連続scheduled run、source別decision往復、
writer rollback、scheduled workflow greenの代わりにはならない。missing source URLの0件も2実run条件を免除しない。

## Closure gaps

| condition | current state |
|---|---|
| unmapped 0 | 全7 source合格 |
| 2 consecutive scheduled parity runs | 全7 source未達 |
| content parity | 全7 source合格（固定Rstart時点） |
| decision round-trip | 白金canary標本のみ。full source別は未達 |
| route boundary | code/testと白金標本のみ。source別実データpack未達 |
| writer rollback | reader rollbackのみ実証。source writer legacy-only dry-run未達 |
| operational green | manual production shadowのみ。scheduled dual-write未配線 |
| public unchanged | 全7 source合格 |
| Koto independent closure review | parity/cutover合格、decision/rollback/2 runは未達 |
| Uchida approval | reader GOのみ。writer stop GOなし |

## Proposed delivery

### B1-C1a: workflow contract PR（状態変更なし）

- 7 sourceの実行順、input lineage、Rstart/Rend、CAS、fresh inbox exportを文書とテストで固定する。
- production workflowの環境変数は既定offのままにする。
- legacy writer、legacy JSON、reader rollback入口を維持する。
- 実workflow fileへwriter commandを追加しない。

### B1-C1b: default-off wiring PR（別レビュー・別GO）

- 日次builderがlegacy JSONを生成した直後に対応adapter/source writerを実行する。
- 1 source 1 CASを維持し、前sourceのRendを次sourceのRstartとして再測定する。
- 最後にfresh S3 DBから `review_inbox.json` をexportする。
- CAS conflict、parity差、unmapped、lifecycle変化、domain/public差でfail closedする。
- scheduled defaultは明示GOまでoff。workflow mergeだけでproduction writeを始めない。

### B1-C2: closure decision pack

- sourceごとに安全なfixtureでaccepted/rejected/hold/needs_researchを保存する。
- 同じ入力とpayload変更入力で再buildし、lifecycle保持を確認する。
- acceptはroute別stagingまで、pending/holdはapply packet 0、unsafe acceptはfail closedを確認する。
- production decisionを使う場合はfixtureとは別の明示GOを必要とする。

### B1-C3: two scheduled observations

各runで次を保存する。

- workflow run ID / commit / started and finished time
- source input SHA、adapter snapshot SHA、stable key set、payload hash
- legacy/current/decision/stale coverageとunmapped 0
- source別parity、inbox totals、decision retention
- Rstart/Rend、CAS result、S3 separate fetch SHA
- integrity/FK/domain counts/public bytes
- collection/evidence countsと説明可能な増減

2回は手動rerunではなく連続した実スケジュールrunを使う。run間でinput SHAが変わること自体は失敗ではなく、
各run内のlineageが閉じ、key/payload変化を説明できることを要求する。

### B1-C4: rollback drill

- source writer flagをoffにしたlegacy-only dry-runをsource別に実行する。
- inbox行やdecisionを削除しない。
- last-good legacy snapshotを再表示できることを確認する。
- 誤publish rollbackはremote checksum固定CASと別fetch監査を使い、forceしない。

### B1-C5: source-by-source writer close

10条件を満たしたsourceだけ、こと独立レビューと内田さんのsource別GO後に停止する。

1. readerは既にinboxだが、legacy writerを追加1 scheduled run残す。
2. 追加run green後にwriter closeを判断する。
3. 最終legacy JSONはread-only snapshotとして保持し、空ファイルで上書きしない。
4. builder削除はB完了後のE cleanupで別判断する。

## Proposed scheduled order

1. legacy builders generate the seven current inputs.
2. official source writer (52 baseline).
3. registered investigation writer (79 baseline).
4. predicted research writer, then remeasure Rstart.
5. predicted date review writer, then remeasure Rstart.
6. missing source URL writer, including the zero-item reconciliation.
7. missing venue writer.
8. historical current-identity writer.
9. fetch final S3 artifact and export fresh `review_inbox.json`.
10. run combined parity/inventory/public audit and retain evidence.

実際のworkflow配線、scheduled flag有効化、decision実証、writer停止はこのplanの実行範囲外であり、
それぞれplan→ことレビュー→内田さんGO→実行→こと再検証を維持する。
