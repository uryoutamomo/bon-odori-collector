# Review Inbox Builder Wiring Plan

作成日: 2026-07-17 JST  
署名: おと（Codex）  
ステータス: ことレビュー待ち（B本丸の実装前plan）

## 目的と境界

B本丸では、判断待ちの**新規発生先**を Master RDB の `review_inbox_items` に一本化し、
内田さんが見る画面を review console の「統合レビュー受信箱」だけにする。

一本化するのは置き場・表示・決定状態であり、判断基準や反映処理を均質化しない。
今年の公式発表など未来系を最優先にし、historical / YouTube / 曲・用語は後順位のまま扱う。
console の決定から Master RDB や公開JSONを直接変更せず、検証済み変更リクエストまたは既存の
domain別stagingへ渡す。

次はBの対象外とする。

- `collect.yml` の収集器そのもの、`send_mail.yml`、現地レポート2ツールの停止
- 公開デプロイ、サイト同期
- DynamoDBイベント候補キューの即時廃止（ローカルキュー移行後に別判定）
- Dで行う開催状態・日付確度の2軸化

## 現在地

2026-07-17の `run_review_console.py --inventory` では、18ソース、pending 284件。
`review_inbox_items` は0件で、schema・JSON export・console表示だけが先に存在し、各builderからの
書き込みと決定の戻し先は未配線。

主な残件は次のとおり。

| 既存ソース | pending | 時間軸 |
|---|---:|---|
| registered event investigation | 78 | 未来優先、一部historical |
| official source | 52 | 未来優先 |
| predicted occurrence research/review | 8 + 8 | 未来 |
| missing venue | 3 | 未来 |
| YouTube active video | 86 | 過去・参考 |
| daily term / song | 28 + 2 | 参考 |
| accepted venue-song missing venue | 14 | 参考 |
| historical promotion | 5 | 過去 |

この284件は「移行対象の残高」であり、そのまま全件を新規扱いにしない。移行時に安定IDでdedupeし、
既決定・自動解決・staleを除いた件だけをpendingとして引き継ぐ。

## 永続化と同時書き込みの前提

現行 `collect.yml` はrun冒頭でS3のMaster RDBをfetchするが、run末尾でRDBをpublishしていない。
したがってbuilderがそのSQLiteへupsertするだけでは、GitHub Actions終了時にinboxが消える。
ローカルreview consoleと日次Actionsが同時に別コピーを書けば、後勝ちで決定や新着を失う危険もある。

B0の最初に、S3 latestを正本とする次の単一writer契約を入れる。

1. run開始時のremote checksumを保存する。
2. 一時ローカルDBへinbox upsertまたはdecision更新を1 transactionで行う。
3. audit / integrity check / parity reportが通った場合だけsnapshotを作る。
4. `master_db_s3_artifact.py publish --expect-remote-checksum <開始時SHA>` でcompare-and-swapする。
5. remote checksumが変わっていたらforce overwriteせず、最新を再fetchしてstable IDで再適用する。

日次builder、ローカルdecision、手動change requestのどれもこのwriter境界を迂回しない。
B0着手前にローカル正本とS3 latestのSHAを比較し、差があれば内田さんGOのもとでどちらを起点にするか決める。
この整合が取れるまでは、workflowへRDB dual-writeを入れない。

## Inbox v2 契約

既存の `inbox_id = stable_id(kind, source_id, source_key)` を維持する。builder再実行で同じ判断対象が
増殖せず、accepted / rejected / hold などpending以外の状態を上書きしない。

実装開始時に schema migration で、少なくとも次を検索可能な列として追加する。

- `time_scope`: `future` / `historical` / `reference`
- `decision`: consoleで選んだ有限値
- `decided_by`, `decided_at`, `closed_at`
- `decision_route`: `change_request` / `domain_stage` / `research_followup` / `no_apply`
- `source_payload_hash`, `last_seen_at`

未知の自由記述をactionにしない。初期kindと主なrouteは次に固定する。

| kind | time_scope | 決定後のroute |
|---|---|---|
| `current_year_confirmation` | future | Aの `confirm_current_year_date` request |
| `predicted_date` | future | 採用は予測RDB builder入力、確定昇格は別途当年公式根拠必須 |
| `official_source` / `source_url` | future優先 | change requestまたはresearch follow-up |
| `venue_review` | future優先 | Aの `update_venue` request |
| `occurrence_creation` | future | 新change type追加まではresearch follow-up |
| `historical_reference` / `historical_quality` | historical | Aの `add_historical_reference` request |
| `youtube_evidence` | historical | Aの `add_song_evidence` またはdomain stage |
| `song` / `term` | reference | 既存の曲・用語staging（Bではapplyを混ぜない） |
| `rare_signal` | future優先 | 非X根拠のresearch follow-up、確定時だけchange request |

PR #36後に唯一残った「盆ダンスフェスティバル2023 / 白金児童遊園」は、
`occurrence_creation` + `time_scope=future` として最初の受け入れ標本にする。2023名称の正規化、
2025実績の正しい開催回への分離、2026候補生成を一つの自動applyにせず、別判断として保持する。

## ソース切替順

各段階は1作業単位1PRで直列にし、前段のmain反映を確認してから次へ進む。

### B0: lifecycleと観測基盤

1. ローカル正本とS3 latestを照合し、checksum CAS付き単一writerを先に作る。
2. schema v2、decision API、pending以外を再生成で戻さないテストを追加する。
3. source adapterの共通interfaceを作る。adapterは既存JSONを入力して正規化itemを返す純粋変換とする。
4. legacy↔inboxの件数・stable key・payload hashを比較するparity reportを追加する。
5. review consoleの決定をinboxへ戻し、route別staged JSONを作る。consoleから直接applyしない。
6. `review_inbox.py` のexportを日次入口の最後で実行できるようにするが、legacy表示はまだ残す。

### B1: 未来の開催判断

最初に次をdual-writeする。

1. official source
2. registered event investigation
3. predicted occurrence research / date review
4. missing source URL / missing venue
5. historical promotionのうち今年の開催回同一性判断が必要なもの

consoleは未来系を `time_scope=future`、優先度、更新時刻の順に先頭表示する。
白金deferredをこの段階で投入し、review→hold/research→再生成後も状態保持、までを実地確認する。

### B2: rare signal / X・RSS

`x_news_digest_for_oto → rare_signal → backcheck → registration candidate` の各中間JSONを、
別々の人間レビュー窓口として扱うのを止める。機械探索と非X裏取りは維持し、人間判断が必要になった
地点だけ `kind=rare_signal` へupsertする。既存staged decision adapterは、inbox decisionを読む形へ替える。

この段階ではDynamoDBキューを削除しない。重複流入をstable keyで抑え、ローカル側のparityが成立した後に
「DynamoDBを収集bufferとして残すか、RDBへ寄せるか」を別PRで判断する。

### B3: YouTube

active video、year backfill、user confirmationを順にdual-writeする。動画ID + target occurrence/yearを
source keyに含め、同じ動画が複数JSONから二重表示されないことを確認する。既存のYouTube日次収集・
API quota制御・automation branchは止めず、判断待ちの出口だけをinboxへ替える。

### B4: 曲・用語と低緊急度backlog

daily/weekly song、term/co-occurrence、accepted venue-song、historical quality、publication gapを移す。
この段階で日次生成のキーボードレビューHTML 2本を新規生成停止候補にする。曲マスタ・用語集への反映は
既存domain stagingを通し、Bで自由形式applyへ変えない。

### B5: 読み先切替と旧キュー閉鎖

1. review consoleの既定表示を統合inboxだけにする。
2. legacy SOURCESは「旧残件」表示へ移し、新規生成物としては読まない。
3. `collect.yml` / weekly / YouTube workflowから、閉鎖条件を満たしたlegacy UI・queue生成とgit addを外す。
4. legacy builder本体は削除せず、まず `legacy/` または手動rollback入口へ移す。
5. Cで導入した `json_fallback_count` は0件を確認したうえで、B完了PRでwarningからhard failへ上げる。

## 旧キューの閉鎖条件

キュー単位で次の全条件を満たすまで、writerもconsole sourceも消さない。

1. **新規parity**: 連続2回の実スケジュールrunで、legacyの新規判断対象とinboxのstable key集合が一致する。
2. **内容parity**: event/year/source URL/recommended actionとpayload hashの差が0。許容差はreportに明記する。
3. **残高移行**: legacy pendingがinbox pending、既決定、stale archiveのいずれかへ全件対応し、unmapped 0。
4. **決定往復**: kindごとにaccept/reject/hold/needs_researchをconsoleで保存し、再build後も状態が不変。
5. **反映境界**: acceptがroute別stagingへ出ること、未レビュー・holdがapply対象にならないことをdry-runで確認。
6. **重複なし**: console上で同じ対象がlegacyとinboxに二重表示されない切替設定を確認。
7. **運用green**: 対象workflowが成功し、収集件数・証拠件数に切替前との説明不能な減少がない。
8. **rollback可能**: legacy writer/readerを最低1日次run分は再有効化でき、復帰手順をrunbookに残す。
9. **独立レビュー**: ことがparity、decision round-trip、workflow出力を確認する。
10. **内田さんGO**: writer停止と既定画面切替は明示GO後に行う。

閉鎖後のlegacy JSONは読み取り専用スナップショットとして一時保持し、次runで空に上書きしない。
削除はB完了とは別のE cleanupで判断する。

## PR単位とゲート

| PR | 変更 | 本番状態変更 |
|---|---|---|
| B0a | local/S3整合確認・checksum CAS writer | 正本起点決定とpublishに内田さんGOが必要 |
| B0b | schema/lifecycle/parity/decision staging | migration applyに内田さんGOが必要 |
| B1 | future系adapter + 白金標本 | dual-writeのみ。旧経路維持 |
| B2 | rare signal adapter | dual-writeのみ。DynamoDB維持 |
| B3 | YouTube adapter | dual-writeのみ。収集維持 |
| B4 | song/term/低緊急度adapter | dual-writeのみ。既存apply維持 |
| B5 | workflow writer停止・console既定切替・fallback hard fail | こと再検証後、内田さん切替GO必須 |

各PRで対象テスト、全テスト、inventory、parity reportを通す。RDB schema / workflowに触るPRは、
日次cron成功直後にmergeし、次cronまでの修正猶予を確保する。正本applyはbackup・audit・guardを通す。

## B完了条件

- 新規の人間判断待ちは `review_inbox_items` だけに入る。
- review consoleの統合inboxから全kindを判断でき、決定が再生成で失われない。
- 未来系が常に過去・参考系より先に表示される。
- 旧pending 284件の対応表が `unmapped=0`。
- 閉鎖対象workflowでlegacy queue/UIの新規生成とcommitが止まる。
- collect / weekly / YouTubeの次回実runがgreenで、証拠収集に欠落がない。
- `json_fallback_count == 0` がhard fail契約になり、公開exportは切替前後でbyte-identical。
- DynamoDBを残す/閉じる判断と、残す場合の責務が文書化される。
- rollback runbook、こと独立検証、内田さん切替GOが揃う。
