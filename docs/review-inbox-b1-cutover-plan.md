# B1 review inbox reader cutover plan

Updated: 2026-07-18 JST
署名: おと（Codex）

## 0. このplanの結論

B1-cutoverで切り替えるのは、まず**ローカルreview consoleのB1系レビュー入力**だけである。
`export_public_events.py`、公開JSON生成、site同期、S3/CloudFront deployは
`review_inbox_items`を読んでおらず、本cutoverの対象外である。

現行コードには実reader切替がまだない。`REVIEW_INBOX_READER_MODE`はsource writerの安全ゲートに
だけ存在し、`legacy`以外を拒否する。review consoleは`data/review_inbox.json`とlegacy JSONを
同時にsource定義へ持つが、modeによる排他制御を実装していない。このため、単に環境変数を
`inbox`へ変えるだけではcutoverにならず、重複表示を招く。

実装と実行を分ける。

1. **B1-cutover-a（コードPR、本番切替なし）**: default `legacy`のreader policy、read-only preview、
   parity gate、canary/full inventory比較を実装する。
2. **B1-cutover-b（内田さんの別GO後）**: `canary`を検証してから`inbox`へ進める。どちらも
   review consoleのread選択だけで、Master RDB、decision、domain、公開JSONへ書かない。

## 1. 正確な切替範囲

### 切り替わるconsumer

- `review_console/data.py::build_inventory`
- `run_review_console.py`のlocal server / `--inventory`
- `scripts/publish_public_data_flow.py`内の`run_review_console.py --inventory`
  - inventoryの入力選択だけが変わる。
  - このflowで先に実行される`export_public_events.py`の出力には影響しない。

### 切り替えないconsumer

- `export_public_events.py`と`review_inbox_adapters.production_wiring.public_projection_digest`
- `.github/workflows/collect.yml`
- site同期、S3/CloudFront deploy
- source adapter / source-scoped writer / CAS publisher
- decision stage、change request、domain apply
- B2〜B4、YouTube、rare signal、song/term、X/RSSなど未移行source

### B1 source mapping

`missing_source_url`は0件だが、閉鎖判定を独立に保つためsourceとして数える。したがって
7 source（非空6 source）・170件である。

| legacy console source | v2 `source_id` | Rend7件数 | cutover対象 |
|---|---|---:|---|
| `official_source` | `official_source` | 52 | yes |
| `registered_event_investigation` | `registered_event_investigation` | 79 | yes |
| `predicted_occurrence_research` | `predicted_occurrence_research` | 8 | yes |
| `predicted_occurrence_date_review` | `predicted_occurrence_date_review` | 12 | yes |
| `missing_source_url` | `missing_source_url` | 0 | yes |
| `missing_occurrence_venue` | `missing_venue` | 3 | yes |
| `historical_promotion_candidate` | `historical_reference` | 16 | yes |

full modeでも、上表以外のlegacy console sourceは残す。B1だけを一括移行し、B2〜B4やB5の
writer cleanupを先取りしない。

## 2. 公開影響

現状の公開影響はゼロである。Rend7の別fetch実体に対する公開projection digestは
`04f92aa2fa7aebc9daa266cc91ced18889784e1ceb408998452678bd328002c6`で、Rend6と同一だった。

B1-cutover-aでは、public exporterがreview inboxをimport/queryしないテストを維持し、
cutover previewの前後で次を必須にする。

- `events_public` exact bytes SHA-256が同一
- public event件数、ID集合、全行内容の差分0
- public exporter読取表に変更0

1 byteでも差があればfail closedする。公開経路を将来v2へ接続する変更はB1-cutoverへ混ぜず、
別plan・別GOとする。

## 3. parity前提とdry-run結果

Rend7 `230205e1ad51d10eeb277a32e22e5a5436129a764079b7a7590de8b2593b34d7`
をS3から別fetchし、各本番runで凍結したadapter snapshot 7つと
`review_inbox_adapters/parity.py --require-parity`で再比較した。

- expected / inbox: `170 / 170`
- missing / extra / content mismatch: `0 / 0 / 0`
- source parity: `7 / 7 true`
- integrity: `ok`
- FK violation: `0`
- decision系non-NULL: `0 / 170`
- review inbox以外のdomain table差分: `0`
- public digest差分: `0`

機械可読の要約は`data/b1_cutover_plan_dry_run_20260718.json`に置く。

cutover実行直前にも同じ検査を再実行する。RstartがRend7から変わっていた場合、古い結果へ
追従せず、最新Rstartを別fetchし、同一input SHAでparityを再証明できる場合だけ進む。
input bytesが変わった場合はadapter snapshotを再生成し、こと再レビューまで停止する。

## 4. B1-cutover-a実装契約

### reader policy

review console専用のpolicyを導入し、defaultは必ず`legacy`とする。

- `legacy`: 現行B1 legacy JSONを読む。v2 B1 rowsは表示対象にしない。
- `canary`: `missing_occurrence_venue`のlegacy 3件だけを`missing_venue` v2 3件へ置換する。
  他のB1 sourceはlegacyのまま。legacyとv2の同一対象を同時表示しない。
- `inbox`: 上表7 legacy sourceを除外し、v2 B1 7 sourceだけを読む。その他sourceは維持する。

実装上は既存のdecision/stage互換を守るため、consoleの`ReviewSource`は単一
`review_inbox`のまま維持する。7 sourceへの分離はraw rowの`source_id`をexact allowlistで
選ぶreader policyと、inventoryの`origin_source_id`別件数で表現する。これにより既存の
`key_fields=(inbox_id, source_id, source_key)`、7種の`option_values`、decision source
`review_inbox`、route別stageを変えずに入力だけを排他できる。

prefix/部分一致は禁止する。特に次の近接名は別sourceとしてテストで固定する。

- `missing_occurrence_venue`（legacy置換元）/ `missing_venue`（v2置換先）/
  `accepted_venue_song_missing_venue`（維持）
- `historical_promotion_candidate`（legacy置換元）/ `historical_reference`（v2置換先）/
  `historical_reference_quality`（維持）

modeはreview consoleプロセスに明示して与え、未知値は起動前に拒否する。writerで使う
`REVIEW_INBOX_READER_MODE`との意味衝突を避けるため、実装PRではconsole専用CLI引数または
`REVIEW_CONSOLE_READER_MODE`を第一候補とする。writer gateはB1-cutoverで緩めず、引き続き
`legacy`以外を拒否する。

### 入力lineage

`data/review_inbox.json`をrepo内の古いMaster DBから暗黙生成してはならない。cutover previewは
operator固定RstartのS3別fetch実体からexportし、少なくとも次を証跡へ記録する。

- Master DB SHA-256 / snapshot ID
- review inbox export SHA-256 / 件数 / source別件数
- 7 legacy input SHA-256
- 7 adapter snapshot SHA-256
- parity report SHA-256
- public projection SHA-256

### decision境界

reader切替は表示入力の選択だけである。

- `decisions.json`を書かない。
- `record_inbox_decision` / `clear_inbox_decision`を呼ばない。
- stage packetを生成しない。
- promotion、change request、domain applyを実行しない。
- acceptedにsafe routeがない場合の既存fail-closedを維持する。

read-only比較は`python3 run_review_console.py --preview-reader-modes`で行う。このコマンドは
3 modeのinventoryをメモリ上で比較してstdoutへ出すだけで、inventory、decision、stage、
source fileを一切書かない。実console起動時だけ`--reader-mode`または
`REVIEW_CONSOLE_READER_MODE`を明示し、未指定時は`legacy`とする。

## 5. 段階実行

### Gate 0: 実行前

1. cron実発火帯`17:20-18:00 JST`外。
2. S3 statusを再実測し、Rstart checksum / snapshot IDを固定。
3. cleanな別pathへfetchし、実体SHA=Rstart、integrity ok、FK0を確認。
4. 7 input SHAとadapter snapshot SHAを固定。
5. exact parity `170/170`, missing/extra/mismatch `0/0/0`。
6. public exact bytes digestを固定。
7. default-off、未使用evidence path、完全一致confirmを検査。

### Gate 1: canary reader

- 置換対象は`missing_occurrence_venue` legacy 3件 ↔ `missing_venue` v2 3件だけ。
- normalized card key、title、event、year、source URL、action、statusの比較差分0を要求。
- console総件数は置換前後で増減0。重複key 0。
- decision/stage/domain/public write 0。
- ことがevidenceと実画面/previewを独立確認する。

canary合格前にfullへ進まない。

### Gate 2: full B1 reader

- 上表7 legacy sourceをv2へ置換。
- B1 subsetは170件、source別`52/79/8/12/0/3/16`。
- legacy/v2二重表示0、unmapped 0、missing/extra/mismatch 0。
- 非B1 sourceの件数・内容hash不変。
- public exact bytes digest不変。
- decision/stage/domain write 0。
- こと独立検証後にcutover完了判定。

## 6. 安全ゲートと停止条件

B1-cutover-bのexecutor/previewには次を要求する。

- default off / `--execute`なしではread previewすらactivateしない
- mode別の完全一致confirm
- dual-write bulk、CAS enabled、legacy writer enabledを明示確認
- reader modeを`canary`または`inbox`として明示
- cron回避
- Rstart固定
- evidence上書き拒否
- force publish経路なし

次のいずれかで即停止する。

- S3実体SHA、snapshot、Rstartの不一致
- parityのmissing / extra / mismatchが1以上
- legacy baselineからcutoverによって増えた重複表示が1以上
- source別件数不一致、unmappedが1以上
- 非B1 source差分
- decision/stage/domain write検出
- public bytes差分
- integrity/FK異常

非B1の既存重複は別のデータ品質課題として記録するが、legacy/canary/inboxの全modeで同一なら
B1-cutoverを誤停止させない。`build_reader_mode_preview`はlegacyの重複ID別件数をbaselineにし、
canary/inboxで増えた分だけを`cutover_introduced_duplicate_item_ids`として停止判定する。

## 7. rollback

reader切替はDBを更新しないため、rollbackはconsole modeを`legacy`へ戻してプロセスを再起動する
だけでよい。目標復旧時間は5分以内とする。

- Master RDBのrollback publishは通常不要。
- canary/full中にdecisionを許可しないため、decision巻き戻しも不要。
- 切替と無関係な外部writerがRstartを変えた場合は、そのrunを混ぜず停止する。
- 万一DB変更が検出された場合はcutover失敗として扱い、既知良好snapshotを現在Rendへの
  `expect-rstart`付きCASで戻す。forceは使わない。

## 8. GO境界

このplanとdry-runは本番切替を行わない。

1. おとがB1-cutover-a実装PRを作る。
2. ことがコード、canary/full preview、parity、public bytes、rollbackを事前レビューする。
3. 内田さんがB1-cutover-b実行GOを出す。
4. おとがcanaryを実行し、ことが独立検証する。
5. canary合格後、おとがfullを実行し、ことが独立検証する。

`collect.yml`変更、writer close、legacy生成停止、fallback hard failはB5-cutoverであり、
B1-cutoverのGOには含めない。
