# Review Inbox B1 Dual-write Plan

作成日: 2026-07-18 JST

署名: おと（Codex）

ステータス: ことレビュー合格、B1-2 default-off runner実装（本番dual-writeは未着手）

## 1. 目的と現在地

B1では、未来系イベントの既存判断待ち生成を止めずに、同じ入力から Master RDB の
`review_inbox_items` へも同時に書く。これを本書では **dual-write** と呼ぶ。

B0は正本適用まで完了している。

- 正本 checksum R1: `55721b7722529c0bd9b9b3f3f7ce868b1681dbcc6e7e8f0ff555d5181e2432e6`
- snapshot: `20260718T020255Z`
- inbox schema: v2、`review_inbox_items` は25列・0行
- adapter共通IF、official source adapter、入力hash付きparity、decision stagingはmain反映済み

B1の目的は新しい判断経路の**観測と往復を並走で証明すること**であり、このplanでは実装しない。
RDB migration、source配線、workflow gate、CAS publish、console切替、legacy停止、公開deploy、
domain apply、dual-write有効化は、ことレビューと内田さんの別GOを受けた後の別PRとする。

## 2. Dual-writeの意味と不変条件

dual-write中は、1回のbuilder入力から次の二つを作る。

1. **legacy側**: 現在のJSON・review UI・既存判断待ち生成を従来どおり更新する。
2. **inbox側**: 同じ確定済み入力bytesをsource adapterで正規化し、`review_inbox_items`へupsertする。

cutoverまではlegacy側が読み先・判断・applyの正規経路である。inboxはshadowであり、次を行わない。

- legacy writer、legacy console source、既存staging、既存applyを止めない。
- inbox decisionからMaster RDBのdomain tableや公開JSONを直接変更しない。
- inboxのacceptを「今年の開催確定」へ自動昇格しない。
- inbox書き込みを理由に公開JSON、site、CloudFrontへ反映しない。

inbox decisionは `review_inbox_decision_stage.py` のroute別packetまでとする。実反映は既存の
change requestまたはdomain stagingのレビュー・GOを改めて通す。

## 3. 最初の標本: 白金deferred

最初の実データ標本は、現在blockingに残る唯一件を固定する。

| 項目 | 値 |
|---|---|
| legacy source | `data/registered_event_investigation_queue.json` |
| source_id | `registered_event_investigation` |
| source_key | `evtinv_d7b5f534c8b3ddd8` |
| occurrence_id | `occ_fbba78bb63034a2f` |
| event | 盆ダンスフェスティバル2023 |
| venue | 白金児童遊園 |
| inbox kind | `occurrence_creation` |
| time_scope | `future` |
| initial route | `research_followup` または `no_apply` |

legacy rowの `event_year=2023`、2025根拠、名称、URLはpayloadにそのまま残す。
`time_scope=future` は「2026開催回を新設するか人が判断する仕事を先に出す」というBの並び順であり、
2023/2025/2026を同じ開催回と認定する意味ではない。adapterは2026 occurrenceを作らない。

白金標本は次の順で確認する。

1. full legacy入力のSHA-256を固定し、同じbytesからcanary snapshotを作る。
2. stable IDでinboxへ1件upsertし、legacy itemとinbox itemの内容parityを0差分にする。
3. consoleで `needs_research` を保存し、`research_followup` packetだけが生成されることを確認する。
4. 同じ入力で再buildし、decision・decided_by・decided_atがpendingへ戻らないことを確認する。
5. payloadだけが変わる再観測では、stable IDとdecisionを保持し、`source_payload_hash`と
   `last_seen_at`だけが新しい観測へ更新されることを確認する。
6. `hold` では `no_apply` になり、domain apply packetが出ないことを確認する。

現行契約では `occurrence_creation` のacceptedに安全なapply routeがない。白金のacceptは実装時も
fail closedとし、`create_occurrence`等の有限change typeが別レビューで定義されるまで受理しない。

B1-3のcanary DoDは、配線、stable ID、0差分parity、`needs_research` / `hold` のdecision往復、
再観測でのlifecycle保持、acceptのfail closedまでとする。accept→domain applyの実行はDoDに含めず、
`create_occurrence` change typeはA拡張の別課題に切り出す。

canary snapshotはfull queue closureの証拠には数えない。snapshotにはfull入力hashに加え、
`selection_mode=canary` と選択source_keyを記録する。後のfull adapterでも同じ
`source_id + source_key + kind`を使うため、白金は新IDを作らず同じ行へ冪等upsertされる。

## 4. ソース配線順

実装は1PR直列とし、前段のmain反映・ことレビュー・必要な内田さんGOを確認して次へ進む。

| 順序 | source adapter / 入力 | shadow開始条件 | 備考 |
|---:|---|---|---|
| 0 | registered investigationの白金canary | adapter単体・stable ID・canary parity | 最初の実データ1件。queue closure判定外 |
| 1 | `official_source` / `official_source_review_candidates.json` | 既存adapterをsource-scoped writerへ接続 | 実装済みadapterを最初のbulk検証に使う |
| 2 | `registered_event_investigation` / `registered_event_investigation_queue.json` | full snapshotで白金を含む全対象parity | canary行は同一IDへ再upsert |
| 3 | `predicted_occurrence_research` | 予測根拠とtarget occurrence/yearを固定 | 予測採用と当年確定を混同しない |
| 4 | `predicted_occurrence_date_review` | researchとは別source_idでparity | date reviewの既存decisionを自動昇格しない |
| 5 | `missing_source_url` | URL欠落queueのstable key確定 | acceptは既存research/change request境界へstage |
| 6 | `missing_venue` | venue候補keyと根拠payload固定 | `update_venue`候補でも直接applyしない |
| 7 | `historical_promotion_current_identity` | 今年の開催回同一性が必要な行だけ明示filter | 純historical残高はB4まで動かさない |

順序0は白金を最初の標本にするための限定canaryである。順序1以降がsource単位のbulk shadowで、
旧キュー閉鎖条件は各full sourceに対して判定する。

## 5. Source-scoped dual-write runner契約

各source実runは次の順を固定する。

1. cron実発火帯 `17:20-18:00 JST` 外で開始する。
2. S3 statusから開始checksum `Rstart` とsnapshot IDを記録する。
3. latestをcleanな一時DBへfetchし、local checksumが `Rstart` と一致することを確認する。
4. legacy builderを一度だけ実行し、出力JSONの生bytesを凍結する。
5. legacy writerはそのbytesを従来経路へ書く。
6. adapterも**同じbytes**を読み、input SHA・byte数・adapter snapshot SHAを記録する。
7. 一時DBの1 transaction内でsource itemをupsertする。domain tableには触れない。
8. source観測集合をexportし、`review_inbox_parity.py --require-parity`を実行する。
9. integrity、FK、table counts、decision保持、public export byte一致を監査する。
10. publish直前にremote checksumがまだ `Rstart` であることを再確認する。
11. 差分がinbox観測だけなら `publish --expect-remote-checksum Rstart` でCAS publishする。
12. 新checksum `Rend` とsnapshotを記録し、latest別fetchで再検証する。

no-op runは新snapshotを作らない。CAS conflict、parity差、監査異常、public差分のいずれかがあれば
publishせず停止する。競合時はforceを使わず、最新を再fetchして同じ凍結入力からstable IDで再適用する。

runnerにはsource単位でdefault offのfeature flagを持たせる。canary、bulk shadow、reader cutover、
legacy writer停止は別flag・別GOにし、一つの切替で複数の安全境界を越えない。

## 6. 観測、stale、残高の契約

current sourceから消えたitemを単なるparity `extra`にし続けないため、実装前にsource観測契約を加える。

- 1runでadapterが返したstable ID集合を `seen` とする。
- 同sourceのpending行で `seen` にないものは即削除せず `stale` 候補として別集計する。
- accepted/rejected/hold/needs_researchのlifecycleはsourceから消えても保持する。
- stale化と削除は同じ操作にしない。旧残高対応表が確定するまで行を物理削除しない。
- parityの「actual current set」は今回の `seen` 集合とし、lifecycle履歴はcoverage reportで別に照合する。

既存 `review_inbox_parity.py` はsource_id全行を比較するため、実装PRでは次のどちらかを明示実装する。

1. `last_seen_at` / run IDでcurrent observationを絞るsource-scoped projection、または
2. current / decided / staleを分けたreconciliation snapshot。

extraを無視するfilterは禁止する。current parity、decision履歴、stale理由の三つが合計してlegacy残高へ
全件対応し、coverage reportの `unmapped_count=0` になることを閉鎖条件とする。

B1-2では選択肢1を実装した。今回runの`observation_id + seen stable IDs`をcurrent projectionとし、
追加・内容変更行は`last_seen_at=observation_id`へ更新する。同一内容の再runはDBを更新せず、run側の
projectionでcurrentを証明するため、新snapshotを作らない。unseen行はpending stale候補または
lifecycle保持へ全件分類し、未分類があればfail closedとする。詳細は
`docs/review-inbox-source-writer.md`を参照する。

## 7. Parityと入力hash系譜

PR #42の `review_inbox_parity.py` と共通adapter契約をそのまま基礎にする。

各reportは最低限次を持つ。

- workflow run ID、commit SHA、source_id、adapter version
- `Rstart`、`Rend`、S3 snapshot ID
- legacy input path、SHA-256、byte数
- adapter snapshot path、SHA-256、selection mode
- expected/inbox件数
- missing / extra / content mismatch件数
- stable `inbox_id` 集合と重複数
- `source_payload_hash` と `last_seen_at`

parityの比較項目は既存どおりkind、time_scope、event name、venue、event year、source URL、
recommended action、canonical payload hashとする。status、decision、reviewer等のlifecycleは内容parityから
除外するが、decision round-trip reportでは必ず別検証する。

**dual-write中の差分ゼロ**は、同一run内で次のすべてを満たすことと定義する。

- legacy builderとadapterが参照したinput SHAが同じ。
- duplicate stable ID = 0。
- missing = 0、extra = 0、content mismatch = 0。
- adapter expected count = current inbox observation count。
- payload hashが全IDで一致する。
- decision済み行のlifecycleが再build前後で不変。

別run間でinput SHAが変わること自体は差分ではない。各run内で入力系譜が閉じており、変化したstable keyと
payload hashが説明できることを確認する。異なるinput SHAのlegacyとinboxを比較してparity合格にしない。

## 8. Source単位の旧キュー閉鎖条件

canaryでは閉鎖しない。full sourceごとに次の全条件を満たすまでlegacy writer・reader・apply経路を維持する。

1. **unmapped 0**: legacy pending全件がinbox current、decision済み、理由付きstaleのどれかに対応する。
2. **2連続実run parity**: 手動rerunではなく、2回連続の実スケジュールrunで差分ゼロ。
3. **内容parity**: stable ID、event/year/source URL/action、payload hashの差が0。
4. **決定往復**: sourceの安全なkindでaccept/reject/hold/needs_researchを保存し、再build後も保持する。
5. **route境界**: acceptは既存route別stagingまで、未review/holdはapply対象0。
6. **rollback実証**: feature flagをoffにしてlegacy-onlyへ戻すdry-runが成功する。
7. **運用green**: workflow、収集件数、証拠件数に説明不能な減少がない。
8. **public不変**: 同一入力日の公開exportがbyte-identical。
9. **こと独立レビュー**: input hash、parity、decision round-trip、rollbackをことが再現する。
10. **内田さんGO**: inbox reader切替とlegacy writer停止はそれぞれ明示GOを得る。

source cutoverは二段階にする。

1. **reader cutover**: consoleの当該sourceをinbox表示へ替えるが、legacy writerはさらに1実run残す。
2. **writer close**: 追加runもgreenならlegacyの新規生成を止め、最後のJSONをread-only snapshotとして保持する。

legacy builder本体やsnapshotはB1で削除しない。削除はE cleanupの別判断とする。

## 9. B1全体cutover条件

B1 implementation PRはshadowまでとし、cutoverは別PR・別GOにする。B1全体のcutover候補は次を満たす。

- B1対象sourceがすべてsource閉鎖条件を満たす。
- future itemのcoverageが `unmapped_count=0`。
- consoleでfutureが先頭表示され、legacyとの二重表示が0。
- decision route別packetと既存apply側dry-runの境界が維持される。
- collect系workflowが2連続green、CAS conflictのfail-closedテストが通る。
- RDBのdomain table countsと公開exportが切替前後で不変。
- `json_fallback_count == 0` を2連続の実exportで確認する。
- fallbackをwarningからhard failへ変えるcutover PRを別にレビューする。
- rollback runbook、こと独立レビュー、内田さんcutover GOが揃う。

hard fail化後に `json_fallback_count > 0` が出た場合は公開準備を失敗させ、最後の正常な公開物を維持する。
警告へ自動降格したりJSON fallbackを黙って再採用したりしない。例外運用には別GOを必要とする。

## 10. Rollback

| 段階 | rollback |
|---|---|
| transaction / audit前 | rollbackしてRDBを破棄。legacy出力だけを維持 |
| CAS conflict | publishせず最新を再fetch。force禁止 |
| shadow中 | sourceのdual-write flagをoff。legacy writer/reader/applyは無変更 |
| reader cutover後 | console readerをlegacyへ戻し、保持snapshotを再表示。inbox decisionは消さない |
| writer close後 | 保持したlegacy writer設定と最終snapshotを再有効化。復帰runで件数を再確認 |
| 誤ったRDB publish後 | remote checksum固定のCAS rollback snapshotを作り、別fetchで再監査 |
| fallback hard fail | last-good publicを維持。fallback warningへ戻すのは別レビュー・別GO |

rollbackでinbox行を一括削除しない。stable IDとdecision履歴を残し、再開時の重複・判断消失を防ぐ。

## 11. D本丸の2軸語彙との境界

`time_scope` はBローカルの**仕事の時間軸と表示優先度**であり、イベントの公開状態ではない。

- `future`: 当年・次年の開催回について人の判断が必要な仕事
- `historical`: 過去年実績を整理する仕事
- `reference`: 曲・用語など開催状態を持たない参考仕事

Dの `current_event_state × date_certainty_tier` はevent occurrence / public projectionの2軸である。
B adapter、inbox schema、consoleはこの2軸を書き換えず、`time_scope`から値を推論しない。

白金のようにsourceの `event_year=2023` でも、判断対象が「2026 occurrenceを作るか」なら
`time_scope=future`になり得る。これは開催済み・未確認・日付確度の宣言ではない。

受け入れテストでは次を固定する。

- `time_scope`を公開JSONへ出さない。
- public exporterがreview inboxを参照しない。
- `time_scope`から`current_event_state` / `date_certainty_tier`への変換表を作らない。
- Dの2軸変更がBのstable ID、payload hash、decision lifecycleを変えない。

## 12. 後続PR案

| PR | 内容 | 本番変更 |
|---|---|---|
| B1-1 | registered investigation adapter、白金fixture、canary lineage/parity | なし、default off |
| B1-2 | source-scoped writer、current/stale reconciliation、CAS/audit runner | なし、default off |
| B1-3a | 白金canaryのproduction配線コード・default-off CLI・FakeStore検証 | なし、実行はB1-3b別GO |
| B1-3b | 白金canaryを1件dual-writeしdecision往復 | 要・内田さん最終GO |
| B1-4 | official source bulk shadow | 要・内田さんGO |
| B1-5 | registered investigation full shadow | 要・内田さんGO |
| B1-6 | predicted research/date review shadow | 要・sourceごとのGO |
| B1-7 | missing source/venue shadow | 要・sourceごとのGO |
| B1-8 | current-identity historical subset shadow | 要・内田さんGO |
| B1-cutover | reader切替→1run監視→writer close | 要・こと再検証＋内田さんGO |
| B5-cutover | B全体writer整理、fallback hard fail、cleanup候補化 | B2-B4後の別GO |

全PRは1本ずつmainへ入れ、実runをまたぐPRを並行させない。schema変更が必要になった場合はB1へ混ぜず、
専用migration plan、dry-run、ことレビュー、内田さんGOを別に立てる。

## 13. B1 planレビュー完了条件

- 白金deferredが最初の標本としてstable key・decision route・fail-closed条件まで定義されている。
- dual-writeがlegacy維持のshadowであり、cutover前に読み先・apply・公開を変えないと明記されている。
- source順、parity入力hash、unmapped 0、2実run、決定往復、rollbackが検証可能である。
- cutoverとfallback hard failが別GOである。
- `time_scope`とDの2軸が衝突しない。
- ことレビュー合格後も、実装開始には内田さんの別GOが必要である。
